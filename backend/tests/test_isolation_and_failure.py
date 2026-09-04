# FILE: backend/tests/test_isolation_and_failure.py
"""Merchant isolation, auth enforcement, and graceful provider-failure escalation."""
from __future__ import annotations

import uuid

from app import db
from app.security import hash_password
from tests.conftest import drain

MERCHANT = "merchant_001"


def test_auth_required(client):
    assert client.get("/api/dashboard/metrics").status_code == 401
    assert client.get("/api/recoveries").status_code == 401


def test_merchant_isolation(client, auth):
    """A user from merchant B cannot see merchant A's recovery events."""
    # Create a recovery for merchant_001.
    res = client.post("/webhooks/simulate", headers=auth,
                      json={"event": "payment.failed", "amount": 300000,
                            "payment_id": "pay_iso", "failure_reason": "insufficient_funds"}).json()
    rec_id = res["recovery_event_id"]
    drain()

    # Create a second merchant + user directly and log in.
    db.execute("INSERT INTO merchants (id, name, environment) VALUES ('merchant_002','Other','test')")
    db.execute("INSERT INTO merchant_connections (merchant_id, connected, webhook_status) "
               "VALUES ('merchant_002', 0, 'inactive')")
    db.execute("INSERT INTO users (id, merchant_id, email, password_hash, role) VALUES (?,?,?,?,'owner')",
               (str(uuid.uuid4()), "merchant_002", "other@example.com", hash_password("pw")))
    tok = client.post("/api/auth/login",
                      json={"email": "other@example.com", "password": "pw"}).json()["access_token"]
    other = {"Authorization": f"Bearer {tok}"}

    # merchant_002 must NOT see merchant_001's recovery (404) and has empty list.
    assert client.get(f"/api/recoveries/{rec_id}", headers=other).status_code == 404
    assert client.get("/api/recoveries", headers=other).json() == []
    # merchant_002 dashboard is all zeros.
    m = client.get("/api/dashboard/metrics", headers=other).json()
    assert m["revenue_at_risk"] == 0


def test_provider_failure_escalates_gracefully(client, auth):
    """Force the mock's failure branch (idempotency key ending in 'f') and assert
    the event escalates with a provider_failure audit — worker never crashes."""
    # We can't easily force the key suffix, so we brute force payment ids until
    # the first attempt's SMART_RETRY key ends in 'f'.
    from app.agent.idempotency import idempotency_key

    target = None
    for i in range(500):
        rid_guess = f"rec_probe_{i}"
        if idempotency_key(event_id=rid_guess, attempt=1, action_type="SMART_RETRY").endswith("f"):
            target = rid_guess
            break
    assert target is not None, "could not find a failing key (statistically impossible)"

    # Insert a recovery event with that exact id so attempt-1 SMART_RETRY fails.
    db.execute("INSERT INTO recovery_events (id, merchant_id, payment_id, order_id, amount, "
               "currency, failure_reason, customer_ref, meta_json, status, correlation_id) "
               "VALUES (?,?,?,?,?,?,?,?,?, 'DETECTED', ?)",
               (target, MERCHANT, "pay_fail", "order_fail", 300000, "INR",
                "insufficient_funds", "c@example.com",
                '{"risk_type":"payment_failure"}', "corr_fail"))
    from app.agent.runner import process_recovery_job
    final = process_recovery_job(target, MERCHANT)  # must not raise
    assert final["outcome"] in {"escalated", "escalate"}

    ev = db.query_one("SELECT status FROM recovery_events WHERE id=?", (target,))
    assert ev["status"] == "ESCALATED"
    pf = db.query_one("SELECT COUNT(*) c FROM audit_log WHERE recovery_event_id=? "
                      "AND action='provider_failure'", (target,))["c"]
    assert pf == 1
