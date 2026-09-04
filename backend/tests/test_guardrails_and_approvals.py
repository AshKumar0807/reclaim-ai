# FILE: backend/tests/test_guardrails_and_approvals.py
"""Guardrails (high-value -> approval), approval idempotency (409), rejection."""
from __future__ import annotations

from app import db
from app.agent import guardrails as gr
from app.agent.state import RecoveryState
from tests.conftest import drain

MERCHANT = "merchant_001"


def test_guardrail_high_value_requires_approval():
    state: RecoveryState = {"merchant_id": MERCHANT, "amount": 25_000_00,  # ₹25,000... 
                            "attempt": 0, "selected_action": "PAYMENT_LINK", "action_params": {}}
    # Set amount above threshold (₹50,000 = 5,000,000 paise)
    state["amount"] = 6_000_000
    out = gr.evaluate(state)
    assert out["guardrail_result"] == "REQUIRE_APPROVAL"


def test_guardrail_max_attempts_denies():
    state: RecoveryState = {"merchant_id": MERCHANT, "amount": 100000, "attempt": 3,
                            "selected_action": "SMART_RETRY", "action_params": {}}
    out = gr.evaluate(state)
    assert out["guardrail_result"] == "DENY"
    assert any("maximum_attempts" in r for r in out["guardrail_reasons"])


def test_guardrail_discount_cap_denies():
    state: RecoveryState = {"merchant_id": MERCHANT, "amount": 100000, "attempt": 0,
                            "selected_action": "BOUNDED_COUPON",
                            "action_params": {"discount_pct": 40}}
    out = gr.evaluate(state)
    assert out["guardrail_result"] == "DENY"


def test_high_value_flows_to_approval_queue_and_is_idempotent(client, auth):
    # A high-value overdue invoice -> REQUIRE_APPROVAL -> appears in queue.
    res = client.post("/webhooks/simulate", headers=auth, json={
        "event": "payment.failed", "amount": 25_000_00 * 4,  # ₹1,00,000
        "failure_reason": "disputed_invoice", "risk_type": "overdue_invoice",
        "payment_id": "pay_highval", "days_overdue": 60}).json()
    rec_id = res["recovery_event_id"]
    drain()

    ev = db.query_one("SELECT status FROM recovery_events WHERE id=?", (rec_id,))
    assert ev["status"] == "APPROVAL_REQUIRED"

    pending = client.get("/api/approvals", headers=auth).json()
    assert len(pending) >= 1
    approval_id = [a["id"] for a in pending if a["recovery_event_id"] == rec_id][0]

    # First approve -> 200
    r1 = client.post(f"/api/approvals/{approval_id}/approve", headers=auth)
    assert r1.status_code == 200
    # Second approve of the SAME approval -> 409 Already processed (idempotent)
    r2 = client.post(f"/api/approvals/{approval_id}/approve", headers=auth)
    assert r2.status_code == 409

    # Exactly one action exists for this event (no double execution).
    n = db.query_one("SELECT COUNT(*) c FROM recovery_actions WHERE recovery_event_id=?",
                     (rec_id,))["c"]
    assert n == 1


def test_rejection_closes_recovery(client, auth):
    res = client.post("/webhooks/simulate", headers=auth, json={
        "event": "payment.failed", "amount": 8_000_00 * 10,  # ₹80,000
        "failure_reason": "disputed_invoice", "risk_type": "overdue_invoice",
        "payment_id": "pay_reject", "days_overdue": 50}).json()
    rec_id = res["recovery_event_id"]
    drain()
    pending = client.get("/api/approvals", headers=auth).json()
    approval_id = [a["id"] for a in pending if a["recovery_event_id"] == rec_id][0]
    r = client.post(f"/api/approvals/{approval_id}/reject", headers=auth)
    assert r.status_code == 200
    ev = db.query_one("SELECT status FROM recovery_events WHERE id=?", (rec_id,))
    assert ev["status"] == "CLOSED_LOST"
