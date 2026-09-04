# FILE: backend/app/agent/idempotency.py
"""Idempotency key derivation (spec 12).

    key = sha256(event_id + attempt + action_type)

Stored under a UNIQUE constraint on recovery_actions.idempotency_key. Same event
+ same attempt + same action => same key => duplicate insert is rejected and the
action is skipped. This is the backbone protecting against duplicate webhooks,
queue retries, worker crashes, repeated approval clicks, and batch reprocessing.
"""
from __future__ import annotations

import hashlib


def idempotency_key(*, event_id: str, attempt: int, action_type: str) -> str:
    raw = f"{event_id}:{attempt}:{action_type}"
    return hashlib.sha256(raw.encode()).hexdigest()
