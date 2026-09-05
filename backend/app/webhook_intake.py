# FILE: backend/app/webhook_intake.py
"""Razorpay webhook intake logic (spec 5 API / spec 5 Architecture).

Order: read raw body -> verify signature -> extract event id -> DEDUPLICATE ->
resolve merchant -> persist payment_event -> (create recovery_event + enqueue
job) OR (attribute outcome for captures) -> return quickly.

Signature verification uses stdlib HMAC-SHA256 (Razorpay's scheme). In the mock
profile (no webhook secret) verification is skipped so the simulation runs
key-free, but the exact same code path persists + dedups + enqueues.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid

from . import audit, db
from .agent import outcome
from .config import get_settings
from .jobs import enqueue_recovery
from .logging_config import get_logger

logger = get_logger("reclaimai.webhook")


def verify_signature(raw_body: bytes, signature: str | None) -> bool:
    """Verify Razorpay webhook signature (HMAC-SHA256 of the raw body)."""
    secret = get_settings().razorpay_webhook_secret
    if not secret:
        return True  # mock/local profile: no secret configured -> accept
    if not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _extract(payload: dict) -> dict:
    """Pull the fields we care about from a Razorpay-shaped webhook payload."""
    event_type = payload.get("event", "")
    entity = (((payload.get("payload") or {}).get("payment") or {}).get("entity")) or {}
    plink = (((payload.get("payload") or {}).get("payment_link") or {}).get("entity")) or {}
    amount = int(entity.get("amount") or plink.get("amount") or payload.get("amount") or 0)
    failure_context = {
        key: entity.get(key)
        for key in ("error_code", "error_description", "error_reason", "error_source",
                    "error_step", "method", "bank", "wallet", "vpa")
        if entity.get(key) is not None
    }
    customer_email = entity.get("email") or payload.get("customer_email")
    customer_contact = entity.get("contact") or payload.get("customer_contact")
    return {
        "event_id": payload.get("id") or f"evt_{uuid.uuid4().hex[:12]}",
        "event_type": event_type,
        "payment_id": entity.get("id") or payload.get("payment_id"),
        "order_id": entity.get("order_id") or payload.get("order_id"),
        "amount": amount,
        "currency": entity.get("currency", "INR"),
        "failure_reason": entity.get("error_reason") or entity.get("error_description")
        or payload.get("failure_reason"),
        "method": entity.get("method"),
        "customer_ref": customer_email or customer_contact or payload.get("customer_ref"),
        "customer_email": customer_email,
        "customer_contact": customer_contact,
        "provider_reference": plink.get("id") or entity.get("id"),
        "failure_context": failure_context,
        "metadata": payload.get("metadata", {}),
    }


def process_webhook(raw_body: bytes, signature: str | None, merchant_id: str,
                    *, verify: bool = False, event_id: str | None = None) -> dict:
    """Full intake pipeline. Returns a small status dict (endpoint returns fast)."""
    if verify and not verify_signature(raw_body, signature):
        return {"status": "invalid_signature", "http": 400}

    try:
        payload = json.loads(raw_body.decode() or "{}")
    except json.JSONDecodeError:
        return {"status": "bad_json", "http": 400}

    info = _extract(payload)
    if event_id:
        info["event_id"] = event_id
    correlation_id = info["metadata"].get("correlation_id") or f"corr_{uuid.uuid4().hex[:12]}"

    # DEDUPLICATION (spec 5): duplicate webhooks are a no-op.
    already = db.query_one("SELECT event_id FROM processed_webhooks WHERE event_id = ?",
                           (info["event_id"],))
    if already:
        logger.info("duplicate_webhook", extra={"ctx_event": info["event_id"]})
        return {"status": "duplicate", "http": 200}
    db.execute("INSERT OR IGNORE INTO processed_webhooks (event_id, merchant_id) VALUES (?,?)",
               (info["event_id"], merchant_id))

    # Persist the payment event (authoritative record).
    db.execute(
        "INSERT OR IGNORE INTO payment_events "
        "(id, merchant_id, payment_id, order_id, event_type, amount, currency, "
        " failure_reason, method, customer_ref, raw_json, correlation_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (info["event_id"], merchant_id, info["payment_id"], info["order_id"],
         info["event_type"], info["amount"], info["currency"], info["failure_reason"],
         info["method"], info["customer_ref"], json.dumps(payload), correlation_id),
    )
    audit.record(merchant_id=merchant_id, entity_type="payment_event",
                 entity_id=info["event_id"], payment_id=info["payment_id"],
                 actor="system", action=f"webhook:{info['event_type']}",
                 correlation_id=correlation_id, publish_realtime=False)

    # Route by event type ---------------------------------------------------- #
    if info["event_type"] in {"payment.captured", "payment_link.paid", "order.paid",
                               "subscription.charged",
                               "invoice.paid"}:
        # Outcome / natural recovery (spec 13/14). Attribute to an open recovery.
        event_id = outcome.apply_payment_captured(
            merchant_id=merchant_id, payment_id=info["payment_id"],
            order_id=info["order_id"],
            amount=info["amount"], provider_reference=info["provider_reference"],
            correlation_id=correlation_id, natural=True)
        return {"status": "captured_processed", "recovery_event_id": event_id, "http": 200}

    if info["event_type"] in {"payment.failed", "subscription.charged.failed",
                              "payment_link.expired", "order.failed", "invoice.expired",
                              "subscription.halted"}:
        # Create a recovery event and enqueue an async job (spec 5).
        rec_id = f"rec_{uuid.uuid4().hex[:12]}"
        risk_type = info["metadata"].get("risk_type", "payment_failure")
        meta = {"risk_type": risk_type,
            "days_overdue": int(info["metadata"].get("days_overdue", 0)),
            "event_type": info["event_type"],
            "failure_context": info["failure_context"],
            "customer_email": info["customer_email"],
            "customer_contact": info["customer_contact"]}
        db.execute(
            "INSERT INTO recovery_events "
            "(id, merchant_id, payment_event_id, payment_id, order_id, amount, currency, "
            " failure_reason, customer_ref, meta_json, status, correlation_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?, 'DETECTED', ?)",
            (rec_id, merchant_id, info["event_id"], info["payment_id"], info["order_id"],
             info["amount"], info["currency"], info["failure_reason"], info["customer_ref"],
             json.dumps(meta), correlation_id),
        )
        audit.record(merchant_id=merchant_id, entity_type="recovery_event",
                     entity_id=rec_id, recovery_event_id=rec_id, payment_id=info["payment_id"],
                     actor="system", action="recovery.detected", event_type="recovery.detected",
                     rationale=f"{info['event_type']} -> recovery created",
                     correlation_id=correlation_id)
        enqueue_recovery(rec_id, merchant_id, correlation_id)  # RETURN QUICKLY, async
        return {"status": "recovery_enqueued", "recovery_event_id": rec_id, "http": 200}

    # Lifecycle events are persisted and audited even when they do not create a
    # recovery. This keeps refunds, disputes, cancellations, and partial events
    # visible for future policy handlers instead of silently dropping them.
    audit.record(merchant_id=merchant_id, entity_type="payment_event",
                 entity_id=info["event_id"], payment_id=info["payment_id"],
                 actor="system", action=f"lifecycle:{info['event_type']}",
                 event_type=f"payment.lifecycle.{info['event_type']}",
                 rationale="Lifecycle event recorded for policy evaluation",
                 correlation_id=correlation_id)
    return {"status": "lifecycle_recorded", "event_type": info["event_type"], "http": 200}
