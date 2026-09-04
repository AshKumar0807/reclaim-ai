# FILE: backend/app/jobs.py
"""Job handler wiring the queue to the LangGraph runner, plus startup helpers."""
from __future__ import annotations

from .agent.runner import process_recovery_job
from .logging_config import get_logger
from .queue import get_queue

logger = get_logger("reclaimai.jobs")


def handle_job(job: dict) -> None:
    """Consume one queue message: {recovery_event_id, merchant_id, correlation_id}."""
    rec_id = job.get("recovery_event_id")
    merchant_id = job.get("merchant_id")
    if not rec_id or not merchant_id:
        logger.warning("bad_job", extra={"ctx_job": str(job)})
        return
    process_recovery_job(rec_id, merchant_id)


def enqueue_recovery(recovery_event_id: str, merchant_id: str,
                     correlation_id: str | None = None) -> None:
    get_queue().publish({
        "recovery_event_id": recovery_event_id,
        "merchant_id": merchant_id,
        "correlation_id": correlation_id,
    })


def start_worker() -> None:
    """Start the in-process consumer (LOCAL profile). For RabbitMQ the standalone
    worker.py process calls this too."""
    get_queue().start_consumer(handle_job)
