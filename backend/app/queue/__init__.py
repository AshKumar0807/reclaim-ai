# FILE: backend/app/queue/__init__.py
"""Queue factory + process-wide singleton.

get_queue() returns the configured provider (local or rabbitmq). The webhook
publishes jobs to it; the worker (in-process for LOCAL, standalone for RabbitMQ)
consumes them.
"""
from __future__ import annotations

from ..config import get_settings
from .base import QueueProvider
from .local import LocalQueue

_queue: QueueProvider | None = None


def get_queue() -> QueueProvider:
    global _queue
    if _queue is None:
        settings = get_settings()
        if settings.queue_provider == "rabbitmq":
            from .rabbitmq import RabbitMQQueue
            _queue = RabbitMQQueue()
        else:
            _queue = LocalQueue()
    return _queue


def reset_queue() -> None:
    """Testing helper to drop the singleton."""
    global _queue
    if _queue is not None:
        try:
            _queue.stop()
        except Exception:
            pass
    _queue = None
