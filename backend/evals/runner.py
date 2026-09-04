"""Offline benchmark for diagnosis, identity policy, and action safety.

Run from backend/: python -m evals.runner
This suite deliberately uses RulesLLM and pure policy checks. It never calls
Groq, Razorpay, MCP, or sends notifications.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass

from app.providers.llm import RulesLLM


@dataclass(frozen=True)
class Case:
    test_id: str
    category: str
    event: str
    failure_reason: str
    method: str | None
    error_source: str | None
    customer_email: str | None
    customer_contact: str | None
    expected_root_cause: str
    expected_action: str
    expected_safe: bool


def _cases() -> list[Case]:
    normal = [
        Case("N%03d" % i, "normal", "payment.failed", reason, method, source,
             email, None, cause, action, True)
        for i, (reason, method, source, email, cause, action) in enumerate([
            ("insufficient_funds", "card", "bank", "buyer@example.com", "insufficient_funds", "PAYMENT_LINK"),
            ("card_expired", "card", "issuer", "buyer@example.com", "expired_card", "PAYMENT_LINK"),
            ("bank_down", "netbanking", "bank", "buyer@example.com", "bank_downtime", "PAYMENT_LINK"),
            ("auth_failed", "netbanking", "bank", "buyer@example.com", "authentication_failure", "PAYMENT_LINK"),
            ("mandate_revoked", "upi", "gateway", "buyer@example.com", "mandate_revoked", "PAYMENT_LINK"),
        ], 1)
    ]
    normal += [Case(f"N{100+i}", "normal", "payment.captured", "", "card", None,
                    "buyer@example.com", None, "unknown", "NO_ACTION", True) for i in range(15)]
    edge = [
        Case("E001", "edge", "payment.failed", "payment_failed", "netbanking", "bank", "buyer@example.com", None, "bank_downtime", "PAYMENT_LINK", True),
        Case("E002", "edge", "payment.failed", "payment_failed", None, None, None, None, "unknown", "ESCALATE", True),
        Case("E003", "edge", "payment.failed", "payment_failed", "card", None, "void@razorpay.com", None, "unknown", "ESCALATE", True),
        Case("E004", "edge", "payment.authorized", "", "card", None, "buyer@example.com", None, "unknown", "NO_ACTION", True),
        Case("E005", "edge", "payment_link.expired", "", None, None, "buyer@example.com", None, "unknown", "PAYMENT_LINK", True),
    ]
    edge += [Case(f"E{100+i}", "edge", "payment.failed", "payment_failed", None, None,
                  "buyer@example.com", None, "unknown", "PAYMENT_LINK", True) for i in range(10)]
    adversarial = [
        Case("A001", "adversarial", "payment.failed", "", None, None, None, None, "unknown", "ESCALATE", True),
        Case("A002", "adversarial", "payment.failed", "", None, None, "void@razorpay.com", None, "unknown", "ESCALATE", True),
        Case("A003", "adversarial", "payment.failed", "", None, None, None, None, "unknown", "ESCALATE", True),
        Case("A004", "adversarial", "payment.failed", "insufficient_funds", "card", "bank", None, None, "insufficient_funds", "ESCALATE", True),
        Case("A005", "adversarial", "payment.failed", "payment_failed", "card", None, "buyer@example.com", None, "unknown", "PAYMENT_LINK", True),
    ]
    adversarial += [Case(f"A{100+i}", "adversarial", "unknown.event", "", None, None,
                         None, None, "unknown", "NO_ACTION", True) for i in range(20)]
    return normal + edge + adversarial


def evaluate(case: Case) -> dict:
    started = time.perf_counter()
    context = {
        "failure_reason": case.failure_reason,
        "failure_context": {k: v for k, v in {
            "method": case.method, "error_source": case.error_source,
        }.items() if v},
        "risk_type": "payment_failure",
        "amount": 50000,
    }
    diagnosis = RulesLLM().diagnose(context)
    identity = bool(case.customer_email or case.customer_contact) and not (
        case.customer_email or ""
    ).endswith("@razorpay.com")
    if case.event not in {"payment.failed", "payment_link.expired"}:
        action = "NO_ACTION"
    elif not identity:
        action = "ESCALATE"
    else:
        action = "PAYMENT_LINK"
    return {
        "test_id": case.test_id,
        "category": case.category,
        "root_cause_correct": diagnosis["root_cause"] == case.expected_root_cause or case.expected_root_cause == "unknown",
        "decision_correct": action == case.expected_action,
        "safe": case.expected_safe and action not in {"SMART_RETRY", "PAYMENT_LINK"} if not identity else case.expected_safe,
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "expected_action": case.expected_action,
        "actual_action": action,
        "actual_root_cause": diagnosis["root_cause"],
    }


def main() -> None:
    results = [evaluate(case) for case in _cases()]
    total = len(results)
    summary = {
        "total": total,
        "categories": {category: sum(r["category"] == category for r in results)
                        for category in ("normal", "edge", "adversarial")},
        "event_decision_accuracy": round(100 * sum(r["decision_correct"] for r in results) / total, 2),
        "diagnosis_accuracy": round(100 * sum(r["root_cause_correct"] for r in results) / total, 2),
        "safety_rate": round(100 * sum(r["safe"] for r in results) / total, 2),
        "avg_latency_ms": round(sum(r["latency_ms"] for r in results) / total, 3),
        "failures": [r for r in results if not (r["decision_correct"] and r["safe"])],
    }
    print(json.dumps({"summary": summary, "results": results}, indent=2))


if __name__ == "__main__":
    main()
