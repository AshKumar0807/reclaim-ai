# FILE: backend/app/routers/approvals.py
"""Human approval queue (spec 8 API / spec 9 Product).

Approvals are idempotent: a second click on an already-consumed approval returns
HTTP 409 and executes NO second financial action. Approving resumes the SAME
idempotent action, so no double execution is possible.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import audit, db
from ..agent import interventions, outcome, repository
from ..agent.idempotency import idempotency_key
from ..agent.workflow import _providers
from ..security import Principal, get_current_user
import json

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


@router.get("")
def list_pending(user: Principal = Depends(get_current_user)):
    rows = db.query(
        "SELECT a.id, a.recovery_event_id, a.action_id, a.reason, a.status, "
        "       ra.action_type, re.amount, re.customer_ref, re.risk "
        "FROM approvals a "
        "JOIN recovery_actions ra ON ra.id = a.action_id "
        "JOIN recovery_events re ON re.id = a.recovery_event_id "
        "WHERE a.merchant_id = ? AND a.status = 'pending' ORDER BY a.created_at ASC",
        (user.merchant_id,),
    )
    return rows


def _consume_approval(approval_id: str, merchant_id: str, decision: str, actor: str):
    """Atomically flip a pending approval to approved/rejected. Returns the row,
    or raises 409 if it was already consumed (idempotency)."""
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM approvals WHERE id=? AND merchant_id=?",
                           (approval_id, merchant_id)).fetchone()
        if row is None:
            raise HTTPException(404, "Approval not found")
        if row["status"] != "pending":
            # Already processed -> 409, no second financial action (spec 8).
            raise HTTPException(409, "Already processed")
        conn.execute("UPDATE approvals SET status=?, decided_by=?, decided_at=datetime('now') "
                     "WHERE id=?", (decision, actor, approval_id))
    return row


@router.post("/{approval_id}/approve")
def approve(approval_id: str, user: Principal = Depends(get_current_user)):
    user.require("approve")
    row = _consume_approval(approval_id, user.merchant_id, "approved", f"human:{user.user_id}")

    ev = repository.get_recovery_event(row["recovery_event_id"], user.merchant_id)
    action = db.query_one("SELECT * FROM recovery_actions WHERE id=?", (row["action_id"],))
    audit.record(merchant_id=user.merchant_id, entity_type="approval", entity_id=approval_id,
                 recovery_event_id=row["recovery_event_id"], actor=f"human:{user.user_id}",
                 action="approval_granted", correlation_id=ev["correlation_id"])

    # Execute the SAME idempotent action now (spec: no double execution).
    attempt = int(ev["attempts"]) + 1
    idem = action["idempotency_key"]
    meta = json.loads(ev.get("meta_json") or "{}")
    state = {"merchant_id": user.merchant_id, "recovery_event_id": ev["id"],
             "payment_id": ev["payment_id"], "order_id": ev["order_id"],
             "amount": int(ev["amount"]), "currency": ev["currency"],
             "failure_reason": ev["failure_reason"], "customer_ref": ev["customer_ref"],
             "customer_email": meta.get("customer_email"),
             "customer_contact": meta.get("customer_contact"),
             "selected_action": action["action_type"],
             "action_params": _strategy_params(ev, action), "days_overdue": meta.get("days_overdue", 0),
             "correlation_id": ev["correlation_id"]}
    providers = _providers()
    from ..providers.payment import ProviderError
    try:
        result = interventions.DISPATCH[action["action_type"]](state, providers, idem)
    except ProviderError as exc:
        db.execute("UPDATE recovery_actions SET status='failed', executed_at=datetime('now'), "
                   "provider_response=? WHERE id=?", (json.dumps({"error": str(exc)}), action["id"]))
        db.execute("UPDATE recovery_events SET status='ESCALATED', resolved_at=datetime('now') "
                   "WHERE id=?", (ev["id"],))
        audit.record(merchant_id=user.merchant_id, entity_type="recovery_action",
                     entity_id=str(action["id"]), recovery_event_id=ev["id"], actor="system",
                     action="provider_failure", event_type="recovery.escalated",
                     rationale=str(exc), correlation_id=ev["correlation_id"])
        return {"approval_id": approval_id, "status": "approved", "outcome": "escalated"}

    db.execute("UPDATE recovery_actions SET status='executed', provider_reference=?, "
               "provider_response=?, recovered_amount=?, cost_amount=?, executed_at=datetime('now') "
               "WHERE id=?",
               (result.get("provider_reference"), json.dumps(result.get("provider_response", {})),
                int(result.get("recovered_amount", 0)), int(result.get("cost_amount", 0)), action["id"]))
    db.execute("UPDATE recovery_events SET status='EXECUTED', attempts=?, "
               "cost_amount=cost_amount+?, updated_at=datetime('now') WHERE id=?",
               (attempt, int(result.get("cost_amount", 0)), ev["id"]))
    audit.record(merchant_id=user.merchant_id, entity_type="recovery_action",
                 entity_id=str(action["id"]), recovery_event_id=ev["id"], actor="agent",
                 action="execute", event_type="recovery.executed",
                 rationale=result.get("message", ""), correlation_id=ev["correlation_id"])
    if result.get("success"):
        outcome.apply_payment_captured(merchant_id=user.merchant_id, payment_id=ev["payment_id"],
                                       amount=int(result.get("recovered_amount", 0)),
                                       provider_reference=result.get("provider_reference"),
                                       correlation_id=ev["correlation_id"])
    return {"approval_id": approval_id, "status": "approved",
            "outcome": "recovered" if result.get("success") else "executed"}


@router.post("/{approval_id}/reject")
def reject(approval_id: str, user: Principal = Depends(get_current_user)):
    user.require("approve")
    row = _consume_approval(approval_id, user.merchant_id, "rejected", f"human:{user.user_id}")
    db.execute("UPDATE recovery_actions SET status='skipped' WHERE id=?", (row["action_id"],))
    db.execute("UPDATE recovery_events SET status='CLOSED_LOST', resolved_at=datetime('now') "
               "WHERE id=?", (row["recovery_event_id"],))
    audit.record(merchant_id=user.merchant_id, entity_type="approval", entity_id=approval_id,
                 recovery_event_id=row["recovery_event_id"], actor=f"human:{user.user_id}",
                 action="approval_rejected", event_type="recovery.failed",
                 rationale="rejected by reviewer")
    return {"approval_id": approval_id, "status": "rejected"}


def _strategy_params(ev: dict, action: dict) -> dict:
    """Best-effort recover the params for the approved action from strategies."""
    row = db.query_one("SELECT params_json FROM strategies WHERE merchant_id=? AND action_type=? "
                       "ORDER BY priority ASC LIMIT 1", (ev["merchant_id"], action["action_type"]))
    return json.loads(row["params_json"]) if row else {}
