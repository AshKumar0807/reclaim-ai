# FILE: backend/app/agent/repository.py
"""Data-access helpers for recovery events / actions / config.

All reads/writes are merchant-scoped. The worker loads AUTHORITATIVE state from
here (spec 10: it does not trust the queue message beyond ids).
"""
from __future__ import annotations

import json

from .. import db


# ----- recovery events ----------------------------------------------------- #
def get_recovery_event(recovery_event_id: str, merchant_id: str) -> dict | None:
    return db.query_one(
        "SELECT * FROM recovery_events WHERE id = ? AND merchant_id = ?",
        (recovery_event_id, merchant_id),
    )


def list_recovery_actions(recovery_event_id: str) -> list[dict]:
    return db.query(
        "SELECT action_type, provider_reference, status FROM recovery_actions "
        "WHERE recovery_event_id = ? ORDER BY id ASC", (recovery_event_id,)
    )


def update_recovery_event(recovery_event_id: str, merchant_id: str, fields: dict) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = :{k}" for k in fields)
    params = {**fields, "rid": recovery_event_id, "mid": merchant_id}
    db.execute(
        f"UPDATE recovery_events SET {cols}, updated_at = datetime('now') "
        f"WHERE id = :rid AND merchant_id = :mid",
        params,
    )


# ----- strategies (config-driven action selection) ------------------------- #
def list_strategies(merchant_id: str) -> list[dict]:
    rows = db.query(
        "SELECT * FROM strategies WHERE merchant_id = ? AND enabled = 1 ORDER BY priority ASC",
        (merchant_id,),
    )
    for r in rows:
        r["params"] = json.loads(r.get("params_json") or "{}")
    return rows


# ----- guardrails ---------------------------------------------------------- #
def load_guardrails(merchant_id: str, scope: str = "global") -> dict:
    defaults = {
        "maximum_attempts": 3,
        "high_value_approval_threshold": 5_000_000,  # ₹50,000 in paise
        "max_discount_pct": 15,
        "daily_spend_cap_inr": 5_000_000,            # ₹50,000 in paise
        "customer_cooldown_hours": 0,
    }
    rows = db.query(
        "SELECT key, value_json FROM guardrails WHERE merchant_id = ? AND scope = ?",
        (merchant_id, scope),
    )
    for r in rows:
        defaults[r["key"]] = json.loads(r["value_json"]).get("value", defaults.get(r["key"]))
    return defaults


# ----- templates ----------------------------------------------------------- #
def get_template(merchant_id: str, channel: str, key: str, locale: str) -> dict | None:
    row = db.query_one(
        "SELECT * FROM templates WHERE merchant_id = ? AND channel = ? AND key = ? AND locale = ?",
        (merchant_id, channel, key, locale),
    )
    if row is None and locale != "en":
        row = db.query_one(
            "SELECT * FROM templates WHERE merchant_id = ? AND channel = ? AND key = ? AND locale = 'en'",
            (merchant_id, channel, key),
        )
    return row


# ----- daily spend (guardrail input) --------------------------------------- #
def spend_today(merchant_id: str) -> int:
    row = db.query_one(
        "SELECT COALESCE(SUM(cost_amount),0) AS s FROM recovery_actions "
        "WHERE merchant_id = ? AND status = 'executed' AND date(executed_at) = date('now')",
        (merchant_id,),
    )
    return int(row["s"] if row else 0)
