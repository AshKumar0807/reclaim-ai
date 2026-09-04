# FILE: backend/app/providers/notification.py
"""NotificationProvider abstraction (spec 17).

Customer-facing messages are rendered from APPROVED TEMPLATES stored per merchant
(spec 11 Product) - never raw LLM output. Default ConsoleNotifier logs the
rendered payload so the simulation needs no SMTP/WhatsApp credentials.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..config import Settings, get_settings
from ..logging_config import get_logger

logger = get_logger("reclaimai.notifier")


class NotificationProvider(ABC):
    name: str

    @abstractmethod
    def send(self, *, channel: str, to: str, subject: str, body: str, meta: dict) -> dict: ...


class ConsoleNotifier(NotificationProvider):
    name = "console"

    def send(self, *, channel: str, to: str, subject: str, body: str, meta: dict) -> dict:
        logger.info("notify", extra={"ctx_channel": channel, "ctx_to": to})
        return {"provider": self.name, "channel": channel, "to": to,
                "subject": subject, "body": body, "delivered": True}


def render_template(body: str, variables: dict) -> str:
    """Safe {placeholder} substitution that leaves unknown keys visible."""
    class _D(dict):
        def __missing__(self, k: str) -> str:
            return "{" + k + "}"
    return body.format_map(_D(variables))


def get_notifier(settings: Settings | None = None) -> NotificationProvider:
    get_settings() if settings is None else settings
    return ConsoleNotifier()
