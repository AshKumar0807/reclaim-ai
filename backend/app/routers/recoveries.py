# FILE: backend/app/routers/recoveries.py
"""Recovery events list + detail with full audit timeline (spec 7 API)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..security import Principal, get_current_user

router = APIRouter(prefix="/api/recoveries", tags=["recoveries"])


@router.get("")
def list_recoveries(
    status: str | None = None,
    risk: str | None = None,
    limit: int = 100,
    user: Principal = Depends(get_current_user),
):
    sql = "SELECT * FROM recovery_events WHERE merchant_id = ?"
    params: list = [user.merchant_id]
    if status:
        sql += " AND status = ?"; params.append(status)
    if risk:
        sql += " AND risk = ?"; params.append(risk)
    sql += " ORDER BY created_at DESC LIMIT ?"; params.append(limit)
    rows = db.query(sql, tuple(params))
    for r in rows:
        r["meta"] = json.loads(r.pop("meta_json", "{}") or "{}")
    return rows


@router.get("/{recovery_id}")
def get_recovery(recovery_id: str, user: Principal = Depends(get_current_user)):
    ev = db.query_one("SELECT * FROM recovery_events WHERE id=? AND merchant_id=?",
                      (recovery_id, user.merchant_id))
    if not ev:
        raise HTTPException(404, "Recovery not found")
    ev["meta"] = json.loads(ev.pop("meta_json", "{}") or "{}")

    actions = db.query("SELECT id, action_type, status, requires_approval, rationale, "
                       "provider_reference, provider_response, recovered_amount, cost_amount, executed_at "
                       "FROM recovery_actions WHERE recovery_event_id=? AND merchant_id=? "
                       "ORDER BY id ASC", (recovery_id, user.merchant_id))
    approvals = db.query("SELECT id, status, reason, decided_by, decided_at "
                         "FROM approvals WHERE recovery_event_id=? AND merchant_id=?",
                         (recovery_id, user.merchant_id))
    timeline = db.query("SELECT actor, action, event_type, rationale, created_at "
                        "FROM audit_log WHERE recovery_event_id=? AND merchant_id=? "
                        "ORDER BY id ASC", (recovery_id, user.merchant_id))
    return {
        "payment": {"payment_id": ev["payment_id"], "order_id": ev["order_id"],
                    "amount": ev["amount"], "currency": ev["currency"],
                    "failure_reason": ev["failure_reason"], "customer_ref": ev["customer_ref"]},
        "diagnosis": ev["diagnosis"], "root_cause": ev["root_cause"],
        "decision": ev["selected_action"], "status": ev["status"],
        "outcome": {"recovered_amount": ev["recovered_amount"], "cost_amount": ev["cost_amount"],
                    "net_recovered": ev["recovered_amount"] - ev["cost_amount"]},
        "actions": actions, "approvals": approvals, "audit_timeline": timeline,
        "meta": ev["meta"],
    }
