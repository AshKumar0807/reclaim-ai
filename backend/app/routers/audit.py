# FILE: backend/app/routers/audit.py
"""Audit query API (spec 9). Append-only; merchant-scoped; filterable."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import db
from ..security import Principal, get_current_user

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
def list_audit(
    recovery_id: str | None = None,
    payment_id: str | None = None,
    action: str | None = None,
    actor: str | None = None,
    event_type: str | None = None,
    limit: int = 200,
    user: Principal = Depends(get_current_user),
):
    sql = "SELECT * FROM audit_log WHERE merchant_id = ?"
    params: list = [user.merchant_id]
    for col, val in (("recovery_event_id", recovery_id), ("payment_id", payment_id),
                     ("action", action), ("actor", actor), ("event_type", event_type)):
        if val:
            sql += f" AND {col} = ?"; params.append(val)
    sql += " ORDER BY id DESC LIMIT ?"; params.append(limit)
    return db.query(sql, tuple(params))
