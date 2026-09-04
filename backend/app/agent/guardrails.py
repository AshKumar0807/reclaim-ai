# FILE: backend/app/agent/guardrails.py
"""Deterministic guardrail engine (spec 11).

Returns exactly one of: ALLOW | DENY | REQUIRE_APPROVAL. The LLM cannot override
this (spec 22). All limits are config-driven (guardrails table). This is the
authorization layer between the model's recommendation and tool execution.
"""
from __future__ import annotations

from . import repository
from .state import RecoveryState

ALLOW = "ALLOW"
DENY = "DENY"
REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


def evaluate(state: RecoveryState) -> dict:
    merchant_id = state["merchant_id"]
    limits = repository.load_guardrails(merchant_id)
    reasons: list[str] = []

    amount = int(state.get("amount", 0))
    attempt = int(state.get("attempt", 0))
    action = state.get("selected_action", "")
    params = state.get("action_params", {})

    # 1) maximum_attempts -> DENY (stop / escalate handled by workflow)
    if attempt >= int(limits["maximum_attempts"]):
        reasons.append(f"maximum_attempts reached ({attempt}/{limits['maximum_attempts']})")
        return {"guardrail_result": DENY, "guardrail_reasons": reasons}

    # 2) opt_out / terminal handled upstream; re-check opt_out flag if present
    if state.get("customer_segment") == "opted_out":
        reasons.append("customer opted out")
        return {"guardrail_result": DENY, "guardrail_reasons": reasons}

    # 3) bounded coupon discount cap + daily spend cap
    if action == "BOUNDED_COUPON":
        pct = float(params.get("discount_pct", 0))
        if pct > float(limits["max_discount_pct"]):
            reasons.append(f"discount {pct}% exceeds cap {limits['max_discount_pct']}%")
            return {"guardrail_result": DENY, "guardrail_reasons": reasons}
        est_cost = int(amount * pct / 100)
        if repository.spend_today(merchant_id) + est_cost > int(limits["daily_spend_cap_inr"]):
            reasons.append("daily spend cap would be exceeded")
            return {"guardrail_result": DENY, "guardrail_reasons": reasons}

    # 4) high-value approval threshold -> REQUIRE_APPROVAL
    if amount >= int(limits["high_value_approval_threshold"]):
        reasons.append(
            f"amount {amount} ≥ approval threshold {limits['high_value_approval_threshold']}"
        )
        return {"guardrail_result": REQUIRE_APPROVAL, "guardrail_reasons": reasons}

    reasons.append("within all limits")
    return {"guardrail_result": ALLOW, "guardrail_reasons": reasons}
