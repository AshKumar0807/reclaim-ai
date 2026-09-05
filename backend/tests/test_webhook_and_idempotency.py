# FILE: backend/tests/test_webhook_and_idempotency.py
"""Webhook dedup, action idempotency, outcome attribution, natural recovery."""
from __future__ import annotations

import json

from app import db, webhook_intake
from app.agent import interventions
from app.agent.idempotency import idempotency_key
from tests.conftest import drain

MERCHANT = "merchant_001"


def _payload(event, payment_id, amount=300000, reason="insufficient_funds", eid=None):
    return {
        "id": eid or f"evt_{payment_id}",
        "event": event,
        "payload": {"payment": {"entity": {
            "id": payment_id, "order_id": f"order_{payment_id}", "amount": amount,
            "currency": "INR", "error_reason": reason, "email": "c@example.com"}}},
        "metadata": {"merchant_id": MERCHANT, "risk_type": "payment_failure"},
    }


def test_duplicate_webhook_is_deduped(client, auth):
    raw = json.dumps(_payload("payment.failed", "pay_dup", eid="evt_dup")).encode()
    r1 = webhook_intake.process_webhook(raw, None, MERCHANT)
    r2 = webhook_intake.process_webhook(raw, None, MERCHANT)  # same event id
    assert r1["status"] == "recovery_enqueued"
    assert r2["status"] == "duplicate"
    # Only ONE recovery event created despite two deliveries.
    n = db.query_one("SELECT COUNT(*) c FROM recovery_events WHERE payment_id='pay_dup'")["c"]
    assert n == 1


def test_idempotency_key_is_deterministic():
    k1 = idempotency_key(event_id="rec_1", attempt=1, action_type="SMART_RETRY")
    k2 = idempotency_key(event_id="rec_1", attempt=1, action_type="SMART_RETRY")
    k3 = idempotency_key(event_id="rec_1", attempt=2, action_type="SMART_RETRY")
    assert k1 == k2 and k1 != k3 and len(k1) == 64


def test_no_duplicate_actions_on_reprocess(client, auth):
    res = client.post("/webhooks/simulate", headers=auth,
                      json={"event": "payment.failed", "amount": 300000,
                            "payment_id": "pay_reproc", "failure_reason": "insufficient_funds"}).json()
    rec_id = res["recovery_event_id"]
    drain()
    # Re-enqueue the SAME event: the workflow must not create a duplicate action.
    from app.jobs import enqueue_recovery
    before = db.query_one("SELECT COUNT(*) c FROM recovery_actions WHERE recovery_event_id=?",
                          (rec_id,))["c"]
    enqueue_recovery(rec_id, MERCHANT)
    drain()
    after = db.query_one("SELECT COUNT(*) c FROM recovery_actions WHERE recovery_event_id=?",
                         (rec_id,))["c"]
    # If the first pass recovered, event is terminal (0 new). If not, attempt+1
    # may create exactly one more — but never a duplicate of the same key.
    total = db.query_one("SELECT COUNT(*) c FROM recovery_actions WHERE recovery_event_id=?",
                         (rec_id,))["c"]
    distinct = db.query_one("SELECT COUNT(DISTINCT idempotency_key) c FROM recovery_actions "
                            "WHERE recovery_event_id=?", (rec_id,))["c"]
    assert total == distinct  # never a duplicate idempotency key
    assert after >= before


def _insert_open_recovery(rec_id: str, payment_id: str, amount: int = 300000) -> None:
    """Create an OPEN recovery directly (no queue/worker) to isolate outcome
    attribution from the async worker in these unit tests."""
    db.execute(
        "INSERT INTO recovery_events (id, merchant_id, payment_id, order_id, amount, currency, "
        "failure_reason, customer_ref, meta_json, status, correlation_id) "
        "VALUES (?,?,?,?,?,?,?,?,?, 'DETECTED', ?)",
        (rec_id, MERCHANT, payment_id, f"order_{payment_id}", amount, "INR",
         "bank_down", "c@example.com", '{"risk_type":"payment_failure"}', "corr"),
    )


def test_natural_recovery_without_intervention():
    """payment.captured arriving for a payment with an OPEN recovery marks it
    RECOVERED even though we never intervened (spec 14)."""
    _insert_open_recovery("rec_natural", "pay_natural")
    raw = json.dumps({
        "id": "evt_capture_natural", "event": "payment.captured",
        "payload": {"payment": {"entity": {"id": "pay_natural", "amount": 300000, "currency": "INR"}}},
        "metadata": {"merchant_id": MERCHANT},
    }).encode()
    webhook_intake.process_webhook(raw, None, MERCHANT)
    ev = db.query_one("SELECT status, recovered_amount FROM recovery_events WHERE id='rec_natural'")
    assert ev["status"] == "RECOVERED"
    assert ev["recovered_amount"] == 300000


def test_capture_is_idempotent():
    """A duplicate capture webhook must not double-count recovery."""
    _insert_open_recovery("rec_cap2", "pay_cap2")
    cap = json.dumps({
        "id": "evt_cap2_a", "event": "payment.captured",
        "payload": {"payment": {"entity": {"id": "pay_cap2", "amount": 300000, "currency": "INR"}}},
        "metadata": {"merchant_id": MERCHANT}}).encode()
    webhook_intake.process_webhook(cap, None, MERCHANT)
    # Second capture with a different event id -> still idempotent at the outcome
    # layer (event already RECOVERED).
    webhook_intake.process_webhook(cap.replace(b"evt_cap2_a", b"evt_cap2_b"), None, MERCHANT)
    rec = db.query_one("SELECT COUNT(*) c FROM recovery_events WHERE payment_id='pay_cap2' "
                       "AND status='RECOVERED'")["c"]
    assert rec == 1


def test_capture_matches_created_razorpay_order_id():
    """A later payment on the recovery-created Razorpay Order settles it."""
    _insert_open_recovery("rec_order_capture", "pay_failed_order")
    action_id = db.execute(
        "INSERT INTO recovery_actions "
        "(merchant_id, recovery_event_id, action_type, idempotency_key, status, provider_reference) "
        "VALUES (?,?,?,?, 'executed', ?)",
        (MERCHANT, "rec_order_capture", "SMART_RETRY", "idem_order_capture", "order_recovery_123"),
    )
    db.execute("UPDATE recovery_events SET status='EXECUTED' WHERE id=?", ("rec_order_capture",))

    before = db.query_one("SELECT status FROM recovery_events WHERE id=?", ("rec_order_capture",))
    assert before["status"] == "EXECUTED"

    captured = json.dumps({
        "id": "evt_capture_recovery_order", "event": "payment.captured",
        "payload": {"payment": {"entity": {
            "id": "pay_new_success", "order_id": "order_recovery_123",
            "amount": 300000, "currency": "INR"}}},
        "metadata": {"merchant_id": MERCHANT},
    }).encode()
    result = webhook_intake.process_webhook(captured, None, MERCHANT)

    assert result["recovery_event_id"] == "rec_order_capture"
    after = db.query_one("SELECT status, recovered_amount FROM recovery_events WHERE id=?",
                         ("rec_order_capture",))
    assert after["status"] == "RECOVERED"
    assert after["recovered_amount"] == 300000


def test_payment_link_retry_cancels_only_active_previous_links(monkeypatch):
    class FakePayment:
        name = "razorpay"

        def __init__(self):
            self.cancelled = []

        def get_payment(self, payment_id):
            return {"customer": {"email": "customer@example.com"}}

        def cancel_payment_link(self, payment_link_id):
            self.cancelled.append(payment_link_id)
            return {"id": payment_link_id, "status": "cancelled"}

        def create_payment_link(self, **kwargs):
            return {"status": "issued", "reference": "plink_new", "short_url": "https://rzp.test/new"}

    class FakeNotifier:
        def send(self, **kwargs):
            return {"status": "sent"}

    payment = FakePayment()
    monkeypatch.setattr(interventions, "_render", lambda *args: "Complete your payment")
    monkeypatch.setattr(interventions.repository, "list_recovery_actions", lambda recovery_id: [
        {"action_type": "PAYMENT_LINK", "provider_reference": "plink_paid",
         "provider_response": '{"status":"paid"}'},
        {"action_type": "PAYMENT_LINK", "provider_reference": "plink_active",
         "provider_response": '{"status":"created"}'},
    ])

    result = interventions.payment_link(
        {"merchant_id": MERCHANT, "recovery_event_id": "rec_links", "amount": 90000,
         "payment_id": "pay_failed", "customer_ref": "customer@example.com",
         "action_params": {}}, payment, FakeNotifier(), "idem_new_link")

    assert payment.cancelled == ["plink_active"]
    assert result["provider_response"]["replaced_links"][0]["result"]["skipped"] is True
    assert result["provider_response"]["replaced_links"][1]["result"]["status"] == "cancelled"
