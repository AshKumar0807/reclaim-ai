# FILE: backend/app/agent/outcome.py
"""Outcome attribution + natural recovery (spec 13/14).

Executed ≠ Recovered. A recovery is only marked RECOVERED when a real payment
outcome (payment.captured / payment-link paid) is matched back to it — either
after our intervention, or spontaneously (the customer just paid: "natural
recovery"). This module is the single place that flips an event to RECOVERED,
called from BOTH the simulation execute path and the real Razorpay webhook.
"""
from __future__ import annotations

from .. import audit, db

TERMINAL = {"RECOVERED", "CLOSED_LOST", "OPTED_OUT"}


def _find_recovery_for_payment(merchant_id: str, payment_id: str | None,
                               provider_reference: str | None) -> dict | None:
    """Match an incoming capture to an open recovery event."""
    if payment_id:
        row = db.query_one(
            "SELECT * FROM recovery_events WHERE merchant_id = ? AND payment_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (merchant_id, payment_id),
        )
        if row:
            return row
    if provider_reference:
        row = db.query_one(
            "SELECT re.* FROM recovery_events re "
            "JOIN recovery_actions ra ON ra.recovery_event_id = re.id "
            "WHERE re.merchant_id = ? AND ra.provider_reference = ? "
            "ORDER BY re.created_at DESC LIMIT 1",
            (merchant_id, provider_reference),
        )
        if row:
            return row
    return None


def apply_payment_captured(*, merchant_id: str, payment_id: str | None,
                           amount: int, provider_reference: str | None = None,
                           correlation_id: str | None = None,
                           natural: bool = False) -> str | None:
    """Mark the matching recovery RECOVERED (idempotently). Returns event id."""
    event = _find_recovery_for_payment(merchant_id, payment_id, provider_reference)
    if event is None:
        return None
    if event["status"] in TERMINAL:
        return event["id"]  # idempotent: already settled, do nothing

    db.execute(
        "UPDATE recovery_events SET status='RECOVERED', recovered_amount=?, "
        "resolved_at=datetime('now'), updated_at=datetime('now') WHERE id=? AND merchant_id=?",
        (amount, event["id"], merchant_id),
    )
    audit.record(
        merchant_id=merchant_id, entity_type="recovery_event", entity_id=event["id"],
        recovery_event_id=event["id"], payment_id=payment_id, actor="system",
        action="payment.captured received",
        event_type="recovery.recovered",
        rationale="natural recovery (no intervention)" if natural else "capture attributed to intervention",
        after={"recovered_amount": amount, "status": "RECOVERED"},
        correlation_id=correlation_id or event.get("correlation_id"),
    )
    return event["id"]
