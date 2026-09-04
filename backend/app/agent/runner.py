# FILE: backend/app/agent/runner.py
"""Worker entry point: process one recovery job through the LangGraph workflow.

The queue message carries only {recovery_event_id, merchant_id} (spec 10). We
load authoritative state from the DB inside the graph's `load` node and never
trust arbitrary state from the message.
"""
from __future__ import annotations

from ..logging_config import get_logger
from .state import RecoveryState
from .workflow import compiled_workflow

logger = get_logger("reclaimai.runner")


def process_recovery_job(recovery_event_id: str, merchant_id: str) -> dict:
    """Run the compiled LangGraph workflow for a single recovery event.

    Returns the final state. Never raises for business/provider failures — those
    are captured inside the graph and turned into FAILED/ESCALATED outcomes.
    """
    state: RecoveryState = {
        "recovery_event_id": recovery_event_id,
        "merchant_id": merchant_id,
        "steps_log": [],
    }
    try:
        final = compiled_workflow.invoke(dict(state))
        logger.info("job_done", extra={"ctx_event": recovery_event_id,
                                        "ctx_outcome": final.get("outcome")})
        return final
    except Exception as exc:  # pragma: no cover - last-resort safety net
        # A truly unexpected error must not kill the worker (spec 15).
        logger.error("job_crashed", extra={"ctx_event": recovery_event_id,
                                            "ctx_error": str(exc)})
        return {"recovery_event_id": recovery_event_id, "outcome": "error", "error": str(exc)}
