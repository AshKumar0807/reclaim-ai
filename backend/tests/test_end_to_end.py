# FILE: backend/tests/test_end_to_end.py
"""End-to-end flow: webhook -> queue -> LangGraph -> outcome -> dashboard."""
from __future__ import annotations

from tests.conftest import drain


def _sim(client, auth, **kw):
    body = {"event": "payment.failed", "amount": 300000,
            "failure_reason": "insufficient_funds", "risk_type": "payment_failure"}
    body.update(kw)
    return client.post("/webhooks/simulate", headers=auth, json=body).json()


def test_full_recovery_pipeline(client, auth):
    res = _sim(client, auth, payment_id="pay_e2e_1")
    assert res["status"] == "recovery_enqueued"
    rec_id = res["recovery_event_id"]
    drain()

    detail = client.get(f"/api/recoveries/{rec_id}", headers=auth).json()
    # The workflow ran all stages.
    actions = [a["action"] for a in detail["audit_timeline"]]
    for step in ("recovery.detected", "detect", "diagnose", "decide", "guardrail_check"):
        assert step in actions
    assert detail["root_cause"] == "insufficient_funds"
    assert detail["decision"] == "SMART_RETRY"
    # Status is a valid terminal/near-terminal state.
    assert detail["status"] in {"RECOVERED", "EXECUTED", "ESCALATED"}


def test_dashboard_metrics_consistent(client, auth):
    for i in range(10):
        _sim(client, auth, payment_id=f"pay_dash_{i}")
    drain()
    m = client.get("/api/dashboard/metrics", headers=auth).json()
    assert m["revenue_at_risk"] == 10 * 300000
    assert 0 <= m["gross_recovered"] <= m["revenue_at_risk"]
    assert 0 <= m["recovery_rate"] <= 100
    assert m["net_recovered"] == m["gross_recovered"] - _total_cost(client, auth)


def _total_cost(client, auth) -> int:
    from app import db
    row = db.query_one("SELECT COALESCE(SUM(cost_amount),0) s FROM recovery_events")
    return int(row["s"])
