# FILE: backend/app/queue/local.py
"""In-process queue (QUEUE_PROVIDER=local) — spec 13 LOCAL profile.

A real, threaded work queue backed by stdlib `queue.Queue` with a background
worker thread, bounded retries, and a dead-letter list. This makes the full
async flow (webhook -> queue -> worker -> LangGraph) genuinely work with zero
infrastructure, mirroring the RabbitMQ semantics the production profile uses.
"""
from __future__ import annotations

import queue
import threading
import time

from ..config import get_settings
from ..logging_config import get_logger
from .base import JobHandler, QueueProvider

logger = get_logger("reclaimai.queue.local")


class LocalQueue(QueueProvider):
    name = "local"

    def __init__(self, max_retries: int | None = None) -> None:
        self._q: "queue.Queue[dict]" = queue.Queue()
        self._dlq: list[dict] = []           # dead-letter (spec 6)
        self._handler: JobHandler | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._max_retries = max_retries or get_settings().max_job_retries

    def publish(self, job: dict) -> None:
        job.setdefault("_retries", 0)
        self._q.put(job)

    def start_consumer(self, handler: JobHandler) -> None:
        self._handler = handler
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="reclaimai-worker", daemon=True)
        self._thread.start()
        logger.info("worker_started")

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._q.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                assert self._handler is not None
                self._handler(job)                     # process (ack on success)
            except Exception as exc:                    # retry with backoff, then DLQ
                job["_retries"] = job.get("_retries", 0) + 1
                if job["_retries"] <= self._max_retries:
                    logger.warning("job_retry", extra={"ctx_retries": job["_retries"],
                                                        "ctx_error": str(exc)})
                    time.sleep(min(2 ** job["_retries"], 5) * 0.05)
                    self._q.put(job)
                else:
                    logger.error("job_dead_lettered", extra={"ctx_error": str(exc)})
                    self._dlq.append({**job, "_error": str(exc)})
            finally:
                self._q.task_done()

    def join(self, timeout: float | None = None) -> None:
        """Block until the queue is drained (used by tests)."""
        end = time.time() + (timeout or 30)
        while time.time() < end:
            if self._q.unfinished_tasks == 0:
                return
            time.sleep(0.02)

    @property
    def dead_letters(self) -> list[dict]:
        return list(self._dlq)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
