# FILE: backend/app/routers/dashboard.py
"""Dashboard metrics (spec 6 API). All merchant-scoped, computed from the DB."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import db
from ..schemas import DashboardMetrics
from ..security import Principal, get_current_user

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

ACTIVE_STATES = ("DETECTED", "DIAGNOSED", "ACTION_SELECTED", "GUARDRAIL_CHECKED",
                 "EXECUTING", "EXECUTED", "APPROVAL_REQUIRED", "WAITING_FOR_OUTCOME")


@router.get("/metrics", response_model=DashboardMetrics)
def metrics(user: Principal = Depends(get_current_user)):
    m = user.merchant_id
    at_risk = db.query_one("SELECT COALESCE(SUM(amount),0) s FROM recovery_events WHERE merchant_id=?",
                           (m,))["s"]
    gross = db.query_one("SELECT COALESCE(SUM(recovered_amount),0) s FROM recovery_events "
                         "WHERE merchant_id=? AND status='RECOVERED'", (m,))["s"]
    cost = db.query_one("SELECT COALESCE(SUM(cost_amount),0) s FROM recovery_events WHERE merchant_id=?",
                        (m,))["s"]
    active = db.query_one(
        f"SELECT COUNT(*) c FROM recovery_events WHERE merchant_id=? AND status IN "
        f"({','.join('?'*len(ACTIVE_STATES))})", (m, *ACTIVE_STATES))["c"]
    pending = db.query_one("SELECT COUNT(*) c FROM approvals WHERE merchant_id=? AND status='pending'",
                           (m,))["c"]
    rate = round(100 * gross / at_risk, 1) if at_risk else 0.0
    return DashboardMetrics(revenue_at_risk=int(at_risk), gross_recovered=int(gross),
                            net_recovered=int(gross - cost), recovery_rate=rate,
                            active_recoveries=int(active), pending_approvals=int(pending))


@router.get("/pipeline")
def pipeline(user: Principal = Depends(get_current_user)):
    """Funnel counts for the recovery pipeline view (spec 6 Product)."""
    m = user.merchant_id

    def cnt(where: str, params: tuple = ()) -> int:
        return db.query_one(f"SELECT COUNT(*) c FROM recovery_events WHERE merchant_id=? {where}",
                            (m, *params))["c"]

    detected = cnt("")
    diagnosed = cnt("AND status NOT IN ('DETECTED')")
    action_selected = cnt("AND selected_action IS NOT NULL")
    approval_required = cnt("AND status='APPROVAL_REQUIRED'")
    executed = cnt("AND status IN ('EXECUTED','RECOVERED','ESCALATED')")
    escalated = cnt("AND status='ESCALATED'")
    recovered = cnt("AND status='RECOVERED'")
    return {"detected": detected, "diagnosed": diagnosed,
            "action_selected": action_selected, "approval_required": approval_required,
            "executed": executed, "escalated": escalated, "recovered": recovered}
