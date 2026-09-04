# FILE: backend/app/agent/workflow.py
"""The LangGraph recovery workflow (spec 7).

Graph shape (spec 7 diagram):

    START -> load -> detect -> diagnose -> decide -> guardrail
      guardrail --ALLOW--------> execute -> record_outcome -> maybe_escalate -> END
      guardrail --REQUIRE------> approval  -> END            (resumes after human decision)
      guardrail --DENY---------> stop      -> END
      load --terminal----------> END                         (short-circuit)

Each node persists authoritative state to Postgres/SQLite and writes an
append-only audit entry (with correlation_id). Idempotency is enforced when the
action row is created (unique key). Provider failures are caught and routed to a
graceful FAILED/ESCALATE outcome — the worker never crashes (spec 15).

This module builds the graph using our LangGraph-compatible engine; if the real
`langgraph` package is installed, get_state_graph() returns it instead and the
identical node functions run unchanged.
"""
from __future__ import annotations

import json

from .. import audit, db
from ..providers.llm import get_llm
from ..providers.notification import get_notifier
from ..providers.payment import ProviderError, get_payment_provider
from . import guardrails as gr
from . import interventions, outcome, repository, steps
from .graph_engine import get_state_graph
from .idempotency import idempotency_key
from .state import RecoveryState

StateGraph, END = get_state_graph()


# --------------------------------------------------------------------------- #
# Node implementations
# --------------------------------------------------------------------------- #
def _providers():
    return {"payment": get_payment_provider(), "notifier": get_notifier(), "llm": get_llm()}


def node_load(state: RecoveryState) -> dict:
    """Load authoritative state from the DB (spec 10). Detect terminal states."""
    ev = repository.get_recovery_event(state["recovery_event_id"], state["merchant_id"])
    if ev is None:
        return {"terminal": True, "outcome": "closed_lost",
                "steps_log": ["load: event not found"]}
    terminal_states = {"RECOVERED", "CLOSED_LOST", "OPTED_OUT", "ESCALATED"}
    meta = json_meta(ev)
    patch = {
        "payment_id": ev["payment_id"], "order_id": ev["order_id"],
        "amount": int(ev["amount"]), "currency": ev["currency"],
        "failure_reason": ev["failure_reason"],
        "risk_type": meta.get("risk_type", "payment_failure"),
        "days_overdue": int(meta.get("days_overdue", 0)),
        "customer_ref": ev["customer_ref"], "attempt": int(ev["attempts"]),
        "correlation_id": ev["correlation_id"],
        "steps_log": state.get("steps_log", []),
    }
    patch["failure_context"] = meta.get("failure_context", {})
    patch["customer_email"] = meta.get("customer_email")
    patch["customer_contact"] = meta.get("customer_contact")
    if not patch["customer_email"] and ev["customer_ref"]:
        candidate = str(ev["customer_ref"])
        if "@" in candidate and not candidate.endswith("@razorpay.com"):
            patch["customer_email"] = candidate
    if ev["status"] in terminal_states:
        patch.update({"terminal": True, "outcome": ev["status"].lower(),
                      "steps_log": patch["steps_log"] + [f"load: terminal ({ev['status']})"]})
    else:
        patch["terminal"] = False
        db.execute("UPDATE recovery_events SET status='DIAGNOSED', updated_at=datetime('now') "
                   "WHERE id=? AND merchant_id=?", (ev["id"], ev["merchant_id"]))
    return patch


def node_detect(state: RecoveryState) -> dict:
    out = steps.detect(state)
    audit.record(merchant_id=state["merchant_id"], entity_type="recovery_event",
                 entity_id=state["recovery_event_id"], recovery_event_id=state["recovery_event_id"],
                 actor="agent", action="detect", event_type="recovery.detected",
                 rationale=f"risk={out['risk']}", correlation_id=state.get("correlation_id"))
    return out


def node_diagnose(state: RecoveryState) -> dict:
    out = steps.diagnose(state, get_llm())
    db.execute("UPDATE recovery_events SET diagnosis=?, root_cause=?, updated_at=datetime('now') "
               "WHERE id=? AND merchant_id=?",
               (out["diagnosis"], out["root_cause"], state["recovery_event_id"], state["merchant_id"]))
    audit.record(merchant_id=state["merchant_id"], entity_type="recovery_event",
                 entity_id=state["recovery_event_id"], recovery_event_id=state["recovery_event_id"],
                 actor="agent", action="diagnose", event_type="recovery.diagnosed",
                 rationale=out["diagnosis"], after={"root_cause": out["root_cause"]},
                 correlation_id=state.get("correlation_id"))
    return out


def node_resolve_identity(state: RecoveryState) -> dict:
    """Verify a real customer destination before any customer-facing action."""
    email = state.get("customer_email")
    contact = state.get("customer_contact")
    source = "webhook" if email or contact else "none"

    # Razorpay test fixtures are not usable customer destinations. Ask the
    # official MCP read tool for the payment record before declaring unresolved.
    if (not contact or (email and email.endswith("@razorpay.com"))) and state.get("payment_id"):
        try:
            payment = _providers()["payment"]
            if payment.name != "mock":
                details = payment.get_payment(state["payment_id"])
                customer = details.get("customer") or details
                fetched_email = customer.get("email")
                fetched_contact = customer.get("contact")
                if fetched_email and not fetched_email.endswith("@razorpay.com"):
                    email = fetched_email
                    source = "mcp"
                if fetched_contact:
                    contact = fetched_contact
                    source = "mcp"
        except Exception as exc:  # noqa: BLE001
            audit.record(merchant_id=state["merchant_id"],
                         entity_type="recovery_event", entity_id=state["recovery_event_id"],
                         recovery_event_id=state["recovery_event_id"], actor="agent",
                         action="identity_lookup_failed", rationale=str(exc),
                         correlation_id=state.get("correlation_id"))

    verified = bool(email or contact) and not (email and email.endswith("@razorpay.com") and not contact)
    status = "verified" if verified else "unresolved"
    if verified:
        rationale = f"Customer destination verified via {source}."
        audit_action = "identity_resolved"
    else:
        rationale = "No verified customer email or phone was available from webhook or payment lookup."
        audit_action = "identity_unresolved"
        db.execute("UPDATE recovery_events SET status='ESCALATED', resolved_at=datetime('now'), "
                   "updated_at=datetime('now') WHERE id=? AND merchant_id=?",
                   (state["recovery_event_id"], state["merchant_id"]))
    audit.record(merchant_id=state["merchant_id"], entity_type="recovery_event",
                 entity_id=state["recovery_event_id"], recovery_event_id=state["recovery_event_id"],
                 actor="agent", action=audit_action, event_type="recovery.identity_checked",
                 rationale=rationale, after={"status": status, "source": source},
                 correlation_id=state.get("correlation_id"))
    return {"customer_email": email, "customer_contact": contact,
            "identity_status": status, "identity_source": source,
            "outcome": "escalated" if not verified else state.get("outcome"),
            "terminal": not verified,
            "steps_log": state.get("steps_log", []) + [f"identity: {status} via {source}"]}


def node_decide(state: RecoveryState) -> dict:
    out = steps.decide(state)
    db.execute("UPDATE recovery_events SET selected_action=?, status='ACTION_SELECTED', "
               "updated_at=datetime('now') WHERE id=? AND merchant_id=?",
               (out["selected_action"], state["recovery_event_id"], state["merchant_id"]))
    audit.record(merchant_id=state["merchant_id"], entity_type="recovery_event",
                 entity_id=state["recovery_event_id"], recovery_event_id=state["recovery_event_id"],
                 actor="agent", action="decide", event_type="recovery.action_selected",
                 rationale=out["decision_rationale"],
                 after={"selected_action": out["selected_action"]},
                 correlation_id=state.get("correlation_id"))
    return out


def node_guardrail(state: RecoveryState) -> dict:
    out = gr.evaluate(state)
    db.execute("UPDATE recovery_events SET status='GUARDRAIL_CHECKED', updated_at=datetime('now') "
               "WHERE id=? AND merchant_id=?", (state["recovery_event_id"], state["merchant_id"]))
    audit.record(merchant_id=state["merchant_id"], entity_type="recovery_event",
                 entity_id=state["recovery_event_id"], recovery_event_id=state["recovery_event_id"],
                 actor="agent", action="guardrail_check",
                 rationale="; ".join(out["guardrail_reasons"]),
                 after={"result": out["guardrail_result"]},
                 correlation_id=state.get("correlation_id"))
    return out


def _create_action(state: RecoveryState, *, requires_approval: bool, status: str) -> int | None:
    """Insert the action row with a unique idempotency key. Returns action id, or
    None if a duplicate already exists (idempotent skip)."""
    attempt = int(state.get("attempt", 0)) + 1
    action_type = state["selected_action"]
    idem = idempotency_key(event_id=state["recovery_event_id"], attempt=attempt,
                           action_type=action_type)
    try:
        action_id = db.execute(
            "INSERT INTO recovery_actions "
            "(merchant_id, recovery_event_id, action_type, idempotency_key, status, "
            " requires_approval, rationale, correlation_id) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (state["merchant_id"], state["recovery_event_id"], action_type, idem, status,
             1 if requires_approval else 0, state.get("decision_rationale", ""),
             state.get("correlation_id")),
        )
        return action_id
    except Exception as exc:  # sqlite3.IntegrityError on UNIQUE clash
        if "UNIQUE" in str(exc).upper():
            return None
        raise


def node_execute(state: RecoveryState) -> dict:
    """Auto-execute path. Bumps attempt, enforces idempotency, runs the tool,
    handles provider failure gracefully, and attributes outcome."""
    attempt = int(state.get("attempt", 0)) + 1
    action_id = _create_action(state, requires_approval=False, status="planned")
    if action_id is None:
        return {"execution_status": "skipped", "outcome": "in_progress",
                "steps_log": state.get("steps_log", []) + ["execute: idempotent-skip"]}

    # Terminal-aware: never clobber a concurrent RECOVERED (natural recovery may
    # arrive via webhook while we're mid-flight — spec 14).
    db.execute("UPDATE recovery_events SET status='EXECUTING', attempts=?, updated_at=datetime('now') "
               "WHERE id=? AND merchant_id=? AND status NOT IN "
               "('RECOVERED','CLOSED_LOST','OPTED_OUT','ESCALATED')",
               (attempt, state["recovery_event_id"], state["merchant_id"]))

    idem = idempotency_key(event_id=state["recovery_event_id"], attempt=attempt,
                           action_type=state["selected_action"])
    providers = _providers()
    try:
        result = interventions.DISPATCH[state["selected_action"]](state, providers, idem)
    except ProviderError as exc:
        # GRACEFUL FAILURE (spec 15): mark FAILED, audit, escalate. Never crash.
        db.execute("UPDATE recovery_actions SET status='failed', provider_response=?, "
                   "executed_at=datetime('now') WHERE id=?",
                   (json.dumps({"error": str(exc)}), action_id))
        audit.record(merchant_id=state["merchant_id"], entity_type="recovery_action",
                     entity_id=str(action_id), recovery_event_id=state["recovery_event_id"],
                     actor="system", action="provider_failure", event_type="recovery.failed",
                     rationale=str(exc), correlation_id=state.get("correlation_id"))
        return {"execution_status": "failed", "action_id": action_id,
                "outcome": "escalate",
                "steps_log": state.get("steps_log", []) + [f"execute: provider_failure {exc}"]}

    # Persist executed action
    db.execute("UPDATE recovery_actions SET status='executed', provider_reference=?, "
               "provider_response=?, recovered_amount=?, cost_amount=?, executed_at=datetime('now') "
               "WHERE id=?",
               (result.get("provider_reference"), json.dumps(result.get("provider_response", {})),
                int(result.get("recovered_amount", 0)), int(result.get("cost_amount", 0)), action_id))
    db.execute("UPDATE recovery_events SET status='EXECUTED', cost_amount=cost_amount+?, "
               "updated_at=datetime('now') WHERE id=? AND merchant_id=? AND status NOT IN "
               "('RECOVERED','CLOSED_LOST','OPTED_OUT','ESCALATED')",
               (int(result.get("cost_amount", 0)), state["recovery_event_id"], state["merchant_id"]))
    audit.record(merchant_id=state["merchant_id"], entity_type="recovery_action",
                 entity_id=str(action_id), recovery_event_id=state["recovery_event_id"],
                 actor="agent", action="execute", event_type="recovery.executed",
                 rationale=result.get("message", ""),
                 after={"recovered_amount": result.get("recovered_amount", 0)},
                 correlation_id=state.get("correlation_id"))

    patch = {"execution_status": "executed", "action_id": action_id,
             "provider_reference": result.get("provider_reference"),
             "recovered_amount": int(result.get("recovered_amount", 0)),
             "cost_amount": int(result.get("cost_amount", 0)),
             "steps_log": state.get("steps_log", []) + [result.get("message", "")]}

    # Outcome attribution (spec 13): a provider "success" produces a capture that
    # is attributed via the outcome path (Executed -> then -> Recovered). In
    # simulation we apply it inline; with real Razorpay it arrives via webhook.
    if result.get("success"):
        outcome.apply_payment_captured(
            merchant_id=state["merchant_id"], payment_id=state.get("payment_id"),
            amount=int(result.get("recovered_amount", 0)),
            provider_reference=result.get("provider_reference"),
            correlation_id=state.get("correlation_id"))
        patch["outcome"] = "recovered"
    else:
        # Not captured. Retry later if attempts remain, else escalate.
        limits = repository.load_guardrails(state["merchant_id"])
        patch["outcome"] = "in_progress" if attempt < int(limits["maximum_attempts"]) else "escalate"
    return patch


def node_approval(state: RecoveryState) -> dict:
    """REQUIRE_APPROVAL path: park a pending approval + action, END the graph.
    A human decision later resumes execution (routers/approvals.py)."""
    action_id = _create_action(state, requires_approval=True, status="pending_approval")
    if action_id is None:
        return {"approval_status": "pending", "outcome": "awaiting_approval",
                "steps_log": state.get("steps_log", []) + ["approval: idempotent-skip"]}
    approval_id = f"appr_{state['recovery_event_id']}_{action_id}"
    db.execute("INSERT OR IGNORE INTO approvals "
               "(id, merchant_id, recovery_event_id, action_id, status, reason) "
               "VALUES (?,?,?,?, 'pending', ?)",
               (approval_id, state["merchant_id"], state["recovery_event_id"], action_id,
                "; ".join(state.get("guardrail_reasons", []))))
    db.execute("UPDATE recovery_events SET status='APPROVAL_REQUIRED', updated_at=datetime('now') "
               "WHERE id=? AND merchant_id=?", (state["recovery_event_id"], state["merchant_id"]))
    audit.record(merchant_id=state["merchant_id"], entity_type="approval",
                 entity_id=approval_id, recovery_event_id=state["recovery_event_id"],
                 actor="agent", action="approval_required", event_type="recovery.approval_required",
                 rationale="; ".join(state.get("guardrail_reasons", [])),
                 correlation_id=state.get("correlation_id"))
    return {"approval_status": "pending", "action_id": action_id, "outcome": "awaiting_approval",
            "steps_log": state.get("steps_log", []) + ["approval: enqueued for human"]}


def node_stop(state: RecoveryState) -> dict:
    """DENY path: stop or escalate depending on why we were denied."""
    reasons = state.get("guardrail_reasons", [])
    escalate = any("maximum_attempts" in r for r in reasons)
    status = "ESCALATED" if escalate else "CLOSED_LOST"
    db.execute("UPDATE recovery_events SET status=?, resolved_at=datetime('now'), "
               "updated_at=datetime('now') WHERE id=? AND merchant_id=?",
               (status, state["recovery_event_id"], state["merchant_id"]))
    audit.record(merchant_id=state["merchant_id"], entity_type="recovery_event",
                 entity_id=state["recovery_event_id"], recovery_event_id=state["recovery_event_id"],
                 actor="agent", action="stop",
                 event_type="recovery.escalated" if escalate else "recovery.failed",
                 rationale="; ".join(reasons), correlation_id=state.get("correlation_id"))
    return {"outcome": status.lower(), "terminal": True}


def node_record_outcome(state: RecoveryState) -> dict:
    """Finalize non-recovered execution outcomes (in_progress / escalate)."""
    if state.get("outcome") == "escalate":
        return {}  # handled by maybe_escalate
    return {}


def node_escalate(state: RecoveryState) -> dict:
    db.execute("UPDATE recovery_events SET status='ESCALATED', resolved_at=datetime('now'), "
               "updated_at=datetime('now') WHERE id=? AND merchant_id=?",
               (state["recovery_event_id"], state["merchant_id"]))
    audit.record(merchant_id=state["merchant_id"], entity_type="recovery_event",
                 entity_id=state["recovery_event_id"], recovery_event_id=state["recovery_event_id"],
                 actor="agent", action="escalate", event_type="recovery.escalated",
                 rationale="provider failure or attempts exhausted",
                 correlation_id=state.get("correlation_id"))
    return {"outcome": "escalated", "terminal": True}


# --------------------------------------------------------------------------- #
# Routers (conditional edges)
# --------------------------------------------------------------------------- #
def route_after_load(state: RecoveryState):
    return "end" if state.get("terminal") else "continue"


def route_after_identity(state: RecoveryState):
    return "end" if state.get("identity_status") == "unresolved" else "continue"


def route_after_guardrail(state: RecoveryState):
    return {"ALLOW": "execute", "REQUIRE_APPROVAL": "approval", "DENY": "stop"}[
        state["guardrail_result"]]


def route_after_execute(state: RecoveryState):
    return "escalate" if state.get("outcome") == "escalate" else "end"


# --------------------------------------------------------------------------- #
# Graph assembly
# --------------------------------------------------------------------------- #
def build_workflow():
    g = StateGraph(RecoveryState)
    g.add_node("load", node_load)
    g.add_node("detect", node_detect)
    g.add_node("diagnose", node_diagnose)
    g.add_node("resolve_identity", node_resolve_identity)
    g.add_node("decide", node_decide)
    g.add_node("guardrail", node_guardrail)
    g.add_node("execute", node_execute)
    g.add_node("approval", node_approval)
    g.add_node("stop", node_stop)
    g.add_node("record_outcome", node_record_outcome)
    g.add_node("escalate", node_escalate)

    g.set_entry_point("load")
    g.add_conditional_edges("load", route_after_load, {"continue": "detect", "end": END})
    g.add_edge("detect", "diagnose")
    g.add_edge("diagnose", "resolve_identity")
    g.add_conditional_edges("resolve_identity", route_after_identity,
                            {"continue": "decide", "end": END})
    g.add_edge("decide", "guardrail")
    g.add_conditional_edges("guardrail", route_after_guardrail,
                            {"execute": "execute", "approval": "approval", "stop": "stop"})
    g.add_conditional_edges("execute", route_after_execute,
                            {"escalate": "escalate", "end": "record_outcome"})
    g.add_edge("record_outcome", END)
    g.add_edge("approval", END)
    g.add_edge("stop", END)
    g.add_edge("escalate", END)
    return g.compile()


# Helpers -------------------------------------------------------------------- #
def json_meta(ev: dict) -> dict:
    try:
        return json.loads(ev.get("meta_json") or "{}")
    except Exception:
        return {}


# Compiled singleton
compiled_workflow = build_workflow()
