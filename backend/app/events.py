# FILE: backend/app/events.py
"""In-process pub/sub for real-time dashboard updates via SSE (spec 15/16 API,
spec 16 Product). The worker publishes recovery.* events; the /api/stream SSE
endpoint fans them out to connected merchant dashboards.

This is intentionally simple (per-merchant subscriber queues). In a multi-node
production deployment you'd back this with Redis pub/sub or Postgres LISTEN; the
publish() call site stays identical.
"""
from __future__ import annotations

import json
import queue
import threading
from dataclasses import dataclass, field

# Canonical realtime event names (API contract §15).
EVENT_NAMES = {
    "recovery.detected",
    "recovery.diagnosed",
    "recovery.action_selected",
    "recovery.approval_required",
    "recovery.executed",
    "recovery.recovered",
    "recovery.failed",
    "recovery.escalated",
}


@dataclass
class _Broker:
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _subs: dict[str, list["queue.Queue[str]"]] = field(default_factory=dict)

    def subscribe(self, merchant_id: str) -> "queue.Queue[str]":
        q: queue.Queue[str] = queue.Queue(maxsize=1000)
        with self._lock:
            self._subs.setdefault(merchant_id, []).append(q)
        return q

    def unsubscribe(self, merchant_id: str, q: "queue.Queue[str]") -> None:
        with self._lock:
            if merchant_id in self._subs and q in self._subs[merchant_id]:
                self._subs[merchant_id].remove(q)

    def publish(self, merchant_id: str, event: str, data: dict) -> None:
        """Deliver an SSE-formatted message to all of a merchant's subscribers."""
        payload = f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
        with self._lock:
            for q in self._subs.get(merchant_id, []):
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    pass  # slow consumer; drop rather than block the worker


broker = _Broker()


def publish(merchant_id: str, event: str, data: dict) -> None:
    broker.publish(merchant_id, event, data)
