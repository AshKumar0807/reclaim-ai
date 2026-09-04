# FILE: backend/app/audit.py
"""Append-only audit trail (spec 9 API / spec 1 & 22 Architecture).

One helper, one shape. Every decision and money-touching action writes an audit
row carrying the correlation_id so a single recovery is traceable end-to-end
(spec 17 Observability). Also publishes the matching realtime event so the
dashboard updates live (spec 15).
"""
from __future__ import annotations

import json

from . import db, events


def record(
    *,
    merchant_id: str,
    entity_type: str,
    entity_id: str,
    actor: str,
    action: str,
    recovery_event_id: str | None = None,
    payment_id: str | None = None,
    event_type: str | None = None,
    rationale: str = "",
    before: dict | None = None,
    after: dict | None = None,
    correlation_id: str | None = None,
    publish_realtime: bool = True,
) -> int:
    """Write one append-only audit entry (and optionally emit a realtime event)."""
    audit_id = db.execute(
        """
        INSERT INTO audit_log
          (merchant_id, recovery_event_id, payment_id, entity_type, entity_id,
           actor, action, event_type, rationale, before_json, after_json, correlation_id)
        VALUES (:m, :rec, :pay, :etype, :eid, :actor, :action, :evt, :rat, :before, :after, :corr)
        """,
        {
            "m": merchant_id, "rec": recovery_event_id, "pay": payment_id,
            "etype": entity_type, "eid": str(entity_id), "actor": actor,
            "action": action, "evt": event_type, "rat": rationale,
            "before": json.dumps(before or {}), "after": json.dumps(after or {}),
            "corr": correlation_id,
        },
    )
    if publish_realtime and event_type in events.EVENT_NAMES:
        events.publish(merchant_id, event_type, {
            "recovery_event_id": recovery_event_id,
            "action": action,
            "rationale": rationale,
            **(after or {}),
        })
    return audit_id
