# FILE: backend/app/agent/steps.py
"""Pure agent steps: detect, diagnose, decide (spec 7/9/10).

These are side-effect-free functions returning partial state updates. The
LangGraph nodes (workflow.py) wrap them with persistence + audit. Keeping the
"thinking" pure makes it independently unit-testable.
"""
from __future__ import annotations

from ..providers.llm import LLMProvider
from ..config import get_settings
from . import repository
from .state import RecoveryState

# Bounded action set (spec 10). The model may only choose from these.
BOUNDED_ACTIONS = {
    "SMART_RETRY", "PAYMENT_LINK", "BOUNDED_COUPON", "HINGLISH_NUDGE", "B2B_RECEIVABLES_CHASER",
}


# --------------------------------------------------------------------------- #
# DETECT
# --------------------------------------------------------------------------- #
def detect(state: RecoveryState) -> dict:
    amount = int(state.get("amount", 0))
    days_overdue = int(state.get("days_overdue", 0))
    if amount >= 2_500_000 or days_overdue > 45:      # ≥ ₹25,000
        risk = "high"
    elif amount >= 500_000 or days_overdue > 15:      # ≥ ₹5,000
        risk = "medium"
    else:
        risk = "low"
    return {"risk": risk, "steps_log": state.get("steps_log", []) + [f"detect: risk={risk}"]}


# --------------------------------------------------------------------------- #
# DIAGNOSE
# --------------------------------------------------------------------------- #
def diagnose(state: RecoveryState, llm: LLMProvider) -> dict:
    context = {
        "risk_type": state.get("risk_type"),
        "failure_reason": state.get("failure_reason"),
        "failure_context": state.get("failure_context", {}),
        "amount": int(state.get("amount", 0)),
        "days_overdue": int(state.get("days_overdue", 0)),
        "customer_segment": state.get("customer_segment", "retail"),
    }
    result = llm.diagnose(context)
    return {
        "root_cause": result["root_cause"],
        "confidence": float(result["confidence"]),
        "diagnosis": result["rationale"],
        "steps_log": state.get("steps_log", []) + [
            f"diagnose: {result['root_cause']} ({result['confidence']:.2f}) via {llm.name}"
        ],
    }


# --------------------------------------------------------------------------- #
# DECIDE (config-driven; model constrained to bounded set)
# --------------------------------------------------------------------------- #
def decide(state: RecoveryState) -> dict:
    merchant_id = state["merchant_id"]
    risk_type = state.get("risk_type", "")
    root_cause = state.get("root_cause", "")
    strategies = repository.list_strategies(merchant_id)

    def score(s: dict) -> tuple[int, int]:
        if s["applies_to_risk_type"] == risk_type and s["applies_to_root_cause"] == root_cause:
            spec = 0
        elif s["applies_to_risk_type"] == risk_type and s["applies_to_root_cause"] == "*":
            spec = 1
        elif s["applies_to_risk_type"] == "*" and s["applies_to_root_cause"] == "*":
            spec = 2
        else:
            spec = 99
        return (spec, s["priority"])

    matched = sorted((s for s in strategies if score(s)[0] < 99), key=score)
    candidates = [s["action_type"] for s in matched] or ["HINGLISH_NUDGE"]

    if matched:
        chosen = matched[0]
        action = chosen["action_type"]
        params = chosen["params"]
        strategy_id = chosen["id"]
        rationale = (f"Root cause '{root_cause}' → strategy '{chosen['name']}' "
                     f"(priority {chosen['priority']}).")
    else:
        action, params, strategy_id = "HINGLISH_NUDGE", {"locale": "hinglish"}, None
        rationale = "No configured strategy matched; defaulting to a soft nudge."

    # Safety: never allow an action outside the bounded set (spec 10/22).
    if action not in BOUNDED_ACTIONS:
        action, params, strategy_id = "HINGLISH_NUDGE", {"locale": "en"}, None
        rationale = f"Selected action was out of bounds; forced safe nudge."

    # A failed payment has no reusable authorization by default. In live
    # Razorpay mode, only an explicit saved-token flow can justify a retry;
    # otherwise use the official payment-link MCP tool.
    if (get_settings().payment_provider == "razorpay"
            and action == "SMART_RETRY"
            and root_cause in {"insufficient_funds", "bank_downtime"}):
        action, params, strategy_id = "PAYMENT_LINK", {"locale": "en"}, None
        rationale = (f"Gateway evidence indicates {root_cause}; no reusable payment authorization "
                     "was supplied, so the agent selected a new Razorpay Payment Link.")

    # Razorpay's generic payment_failed event does not identify a recoverable
    # cause. A new payment link is actionable; blindly creating another order
    # is not, so prefer the customer-facing fallback in that case.
    has_gateway_evidence = bool(state.get("failure_context"))
    if not has_gateway_evidence and (state.get("failure_reason") or "").lower() in {"", "payment_failed"}:
        action, params, strategy_id = "PAYMENT_LINK", {"locale": "en"}, None
        rationale = "Gateway supplied no specific failure reason; selected a new payment link."

    return {
        "candidate_actions": candidates,
        "selected_action": action,
        "action_params": params,
        "strategy_id": strategy_id,
        "decision_rationale": rationale,
        "steps_log": state.get("steps_log", []) + [f"decide: {action}"],
    }
