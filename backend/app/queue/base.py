# FILE: backend/app/queue/base.py
"""Queue abstraction (spec 6). The webhook publishes a job; a worker consumes it.

The message is intentionally minimal — {recovery_event_id, merchant_id,
correlation_id}. The queue holds WORK, not authoritative business state.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

JobHandler = Callable[[dict], None]


class QueueProvider(ABC):
    name: str

    @abstractmethod
    def publish(self, job: dict) -> None:
        """Enqueue a recovery job."""

    @abstractmethod
    def start_consumer(self, handler: JobHandler) -> None:
        """Begin consuming jobs, dispatching each to `handler`."""

    @abstractmethod
    def stop(self) -> None:
        """Stop consuming and release resources."""
