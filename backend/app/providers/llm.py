# FILE: backend/app/providers/llm.py
"""LLMProvider abstraction (spec 9/10/17/22).

CRITICAL SAFETY INVARIANT (spec 22): the LLM RECOMMENDS; it never authorizes or
executes. It only returns a diagnosis + a ranked subset of the EXISTING bounded
action set. Guardrails (deterministic) authorize; tools execute.

    RulesLLM  - deterministic, zero-key. Guarantees the demo always works and
                makes batch metrics reproducible.
    GroqLLM   - free-tier Llama via Groq's OpenAI-compatible API, degrades to
                RulesLLM on any error/timeout so the workflow never stalls.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod

import httpx

from ..config import Settings, get_settings
from ..logging_config import get_logger

logger = get_logger("reclaimai.llm")

# The ONLY root causes the diagnosis step may emit (bounded output space).
KNOWN_ROOT_CAUSES = [
    "insufficient_funds", "bank_downtime", "expired_card", "authentication_failure",
    "price_sensitivity", "distraction_abandonment", "mandate_revoked",
    "cashflow_delay", "disputed_invoice", "unknown",
]


class LLMProvider(ABC):
    name: str

    @abstractmethod
    def diagnose(self, context: dict) -> dict:
        """Return {root_cause, confidence, rationale}."""


class RulesLLM(LLMProvider):
    name = "rules"

    _MAP = {
        "insufficient_funds": ("insufficient_funds", 0.9),
        "low_balance": ("insufficient_funds", 0.85),
        "bank_down": ("bank_downtime", 0.88),
        "gateway_timeout": ("bank_downtime", 0.8),
        "card_expired": ("expired_card", 0.95),
        "auth_failed": ("authentication_failure", 0.82),
        "otp_timeout": ("authentication_failure", 0.75),
        "do_not_honor": ("authentication_failure", 0.7),
        "mandate_revoked": ("mandate_revoked", 0.9),
    }

    def diagnose(self, context: dict) -> dict:
        reason = (context.get("failure_reason") or "").lower()
        details = context.get("failure_context") or {}
        description = (details.get("error_description") or "").lower()
        source = (details.get("error_source") or "").lower()
        method = (details.get("method") or "").lower()
        if source == "bank" or method == "netbanking" or "bank error" in description:
            evidence = ", ".join(f"{key}={value}" for key, value in details.items())
            return {"root_cause": "bank_downtime", "confidence": 0.92,
                    "rationale": f"Razorpay gateway evidence indicates a bank-side failure ({evidence})."}
        risk_type = context.get("risk_type")
        if reason in self._MAP:
            cause, conf = self._MAP[reason]
            return {"root_cause": cause, "confidence": conf,
                    "rationale": f"Failure reason '{reason}' maps to {cause}."}
        if risk_type == "checkout_abandonment":
            amount = int(context.get("amount", 0))
            if amount > 500_000:  # > ₹5,000 in paise
                return {"root_cause": "price_sensitivity", "confidence": 0.6,
                        "rationale": "High-value cart abandoned; likely price hesitation."}
            return {"root_cause": "distraction_abandonment", "confidence": 0.55,
                    "rationale": "Low-value cart abandoned; likely distraction."}
        if risk_type == "overdue_invoice":
            days = int(context.get("days_overdue", 0))
            if days > 45:
                return {"root_cause": "disputed_invoice", "confidence": 0.5,
                        "rationale": f"{days} days overdue; possible dispute."}
            return {"root_cause": "cashflow_delay", "confidence": 0.65,
                    "rationale": f"{days} days overdue; typical B2B cashflow delay."}
        if risk_type == "subscription_failure":
            return {"root_cause": "mandate_revoked" if "mandate" in reason else "expired_card",
                    "confidence": 0.6, "rationale": "Renewal failed; card/mandate cause."}
        return {"root_cause": "unknown", "confidence": 0.3, "rationale": "No strong signal."}


class GroqLLM(LLMProvider):
    name = "groq"
    ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, api_key: str, model: str, timeout: float) -> None:
        self._key = api_key
        self._model = model
        self._timeout = timeout
        self._fallback = RulesLLM()

    def diagnose(self, context: dict) -> dict:
        system = (
            "You are a payments risk analyst. Return STRICT JSON with keys "
            "root_cause, confidence (0-1), rationale. root_cause MUST be one of: "
            + ", ".join(KNOWN_ROOT_CAUSES) + ". Use the structured gateway fields "
            "error_code, error_description, error_reason, error_source, error_step, "
            "method, bank, wallet, and vpa as evidence; do not infer a generic cause "
            "when those fields identify a bank or authentication failure."
        )
        try:
            r = httpx.post(self.ENDPOINT, headers={"Authorization": f"Bearer {self._key}"},
                           json={"model": self._model, "temperature": 0.1,
                                 "response_format": {"type": "json_object"},
                                 "messages": [{"role": "system", "content": system},
                                              {"role": "user", "content": json.dumps(context, default=str)}]},
                           timeout=self._timeout)
            r.raise_for_status()
            data = json.loads(r.json()["choices"][0]["message"]["content"])
            cause = data.get("root_cause", "unknown")
            if cause not in KNOWN_ROOT_CAUSES:
                cause = "unknown"
            return {"root_cause": cause, "confidence": float(data.get("confidence", 0.5)),
                    "rationale": data.get("rationale", "")[:500]}
        except Exception as exc:  # noqa: BLE001 — degrade, never break the workflow
            logger.warning("llm_fallback", extra={"ctx_error": str(exc)})
            return self._fallback.diagnose(context)


def get_llm(settings: Settings | None = None) -> LLMProvider:
    settings = settings or get_settings()
    if settings.llm_provider == "groq" and settings.groq_api_key:
        return GroqLLM(settings.groq_api_key, settings.llm_model, settings.llm_timeout_seconds)
    return RulesLLM()
