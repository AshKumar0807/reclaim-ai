"""Identity resolution must precede customer-facing recovery actions."""
from __future__ import annotations

from app import db
from app.agent.runner import process_recovery_job


MERCHANT = "merchant_001"


def test_unresolved_identity_escalates_without_action():
    recovery_id = "rec_unresolved_identity"
    db.execute(
        "INSERT INTO recovery_events (id, merchant_id, payment_id, order_id, amount, "
        "currency, failure_reason, customer_ref, meta_json, status, correlation_id) "
        "VALUES (?,?,?,?,?,?,?,?,?, 'DETECTED', ?)",
        (recovery_id, MERCHANT, "pay_identity_unknown", "order_identity_unknown", 10000,
         "INR", "payment_failed", None,
         '{"risk_type":"payment_failure"}', "corr_identity_unknown"),
    )

    result = process_recovery_job(recovery_id, MERCHANT)

    assert result["outcome"] == "escalated"
    event = db.query_one("SELECT status FROM recovery_events WHERE id=?", (recovery_id,))
    assert event["status"] == "ESCALATED"
    actions = db.query_one(
        "SELECT COUNT(*) AS count FROM recovery_actions WHERE recovery_event_id=?",
        (recovery_id,),
    )
    assert actions["count"] == 0
    identity = db.query_one(
        "SELECT COUNT(*) AS count FROM audit_log WHERE recovery_event_id=? "
        "AND action='identity_unresolved'",
        (recovery_id,),
    )
    assert identity["count"] == 1
