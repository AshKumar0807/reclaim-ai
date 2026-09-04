# FILE: backend/app/agent/state.py
"""LangGraph workflow state (spec 8).

Business/workflow fields ONLY. Secrets and raw provider credentials must never
appear here (spec 4/8/21). Amounts are integer paise (exact money).
"""
from __future__ import annotations

from typing import Any, TypedDict


class RecoveryState(TypedDict, total=False):
    # identity / scope
    merchant_id: str
    recovery_event_id: str
    payment_id: str
    order_id: str
    correlation_id: str

    # payment facts
    amount: int
    currency: str
    failure_reason: str
    risk_type: str          # payment_failure | checkout_abandonment | ...
    days_overdue: int
    customer_ref: str
    customer_email: str
    customer_contact: str
    identity_status: str       # verified | unresolved
    identity_source: str       # webhook | mcp | none
    customer_segment: str

    # diagnosis
    diagnosis: str
    root_cause: str
    confidence: float

    # decision
    candidate_actions: list[str]
    selected_action: str
    strategy_id: int | None
    action_params: dict[str, Any]
    decision_rationale: str

    # guardrails
    guardrail_result: str   # ALLOW | DENY | REQUIRE_APPROVAL
    guardrail_reasons: list[str]

    # execution
    attempt: int
    approval_status: str    # none | pending | approved | rejected
    action_id: int | None
    execution_status: str   # none | executed | failed | skipped
    provider_reference: str
    provider_response: dict[str, Any]
    recovered_amount: int
    cost_amount: int

    # outcome
    outcome: str            # detected | recovered | failed | escalated | closed_lost | awaiting_approval
    terminal: bool
    steps_log: list[str]
