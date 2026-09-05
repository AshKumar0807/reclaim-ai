# FILE: backend/app/providers/payment.py
"""PaymentProvider abstraction (spec 12 / 17).

The LangGraph workflow depends ONLY on this interface, never on Razorpay
directly. Two implementations:

    MockPaymentProvider   - deterministic, zero-key simulation (default)
    RazorpayProvider      - real Razorpay TEST-mode via httpx

Credentials live server-side and are injected here; they never enter LangGraph
state, LLM prompts, or audit logs (spec 4 / 21).
"""
from __future__ import annotations

import hashlib
import asyncio
import json
import os
import sys
import time
from abc import ABC, abstractmethod

import httpx

from ..config import Settings, get_settings


class ProviderError(Exception):
    """Raised on a (simulated or real) provider failure so the workflow can
    handle it gracefully: mark FAILED -> audit -> retry/escalate (spec 15)."""


class PaymentProvider(ABC):
    name: str

    @abstractmethod
    def retry_payment(self, *, amount: int, idempotency_key: str, meta: dict) -> dict: ...

    @abstractmethod
    def create_payment_link(self, *, amount: int, idempotency_key: str, meta: dict) -> dict: ...

    @abstractmethod
    def get_payment(self, payment_id: str) -> dict: ...

    @abstractmethod
    def cancel_payment_link(self, payment_link_id: str) -> dict: ...

    def expire_payment_link(self, payment_link_id: str) -> dict:
        """Backward-compatible alias for older provider integrations."""
        return self.cancel_payment_link(payment_link_id)


class MockPaymentProvider(PaymentProvider):
    """Deterministic mock. Outcome is a stable function of the idempotency key so
    a re-run reproduces identical results (honest, repeatable metrics)."""

    name = "mock"

    def __init__(self, success_rate: float, seed: int) -> None:
        self._rate = success_rate
        self._seed = seed

    def _roll(self, key: str, boost: float = 0.0) -> bool:
        digest = hashlib.sha256(f"{self._seed}:{key}".encode()).hexdigest()
        val = int(digest[:8], 16) / 0xFFFFFFFF
        return val < min(0.98, self._rate + boost)

    def retry_payment(self, *, amount: int, idempotency_key: str, meta: dict) -> dict:
        # Deterministically exercise the provider-failure path for a small slice
        # (keys ending in 'f') so graceful failure/escalation is demonstrable.
        if idempotency_key.endswith("f"):
            raise ProviderError("gateway_timeout: acquirer did not respond")
        ok = self._roll(idempotency_key)
        return {"provider": self.name, "idempotency_key": idempotency_key,
                "status": "captured" if ok else "failed", "amount": amount,
                "reference": f"pay_mock_{idempotency_key[:10]}"}

    def create_payment_link(self, *, amount: int, idempotency_key: str, meta: dict) -> dict:
        ok = self._roll(idempotency_key, boost=0.18)  # links convert better
        short = hashlib.sha1(idempotency_key.encode()).hexdigest()[:10]
        return {"provider": self.name, "idempotency_key": idempotency_key,
                "status": "paid" if ok else "issued",
                "reference": f"plink_mock_{short}",
                "short_url": f"https://rzp.test/i/{short}", "amount": amount}

    def get_payment(self, payment_id: str) -> dict:
        return {"provider": self.name, "id": payment_id, "status": "unknown"}

    def cancel_payment_link(self, payment_link_id: str) -> dict:
        return {"provider": self.name, "id": payment_link_id, "status": "cancelled"}


class RazorpayProvider(PaymentProvider):
    """Real Razorpay TEST-mode client (httpx + Basic auth). Only used when
    PAYMENT_PROVIDER=razorpay and keys are present."""

    name = "razorpay"
    BASE = "https://api.razorpay.com/v1"

    def __init__(self, key_id: str, key_secret: str, timeout: float = 15.0) -> None:
        self._auth = (key_id, key_secret)
        self._timeout = timeout

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.BASE, auth=self._auth, timeout=self._timeout)

    def retry_payment(self, *, amount: int, idempotency_key: str, meta: dict) -> dict:
        # A saved-token/mandate charge in real life; in test mode we create an
        # order so the flow is demonstrable end-to-end.
        try:
            with self._client() as c:
                r = c.post("/orders", json={"amount": amount, "currency": "INR",
                                            # Razorpay receipt values are limited
                                            # to 40 characters; our idempotency
                                            # hash is 64 characters.
                                            "receipt": f"reclaim_{idempotency_key[:32]}"})
                r.raise_for_status()
                order = r.json()
            return {"provider": self.name, "idempotency_key": idempotency_key,
                    "status": "created", "reference": order.get("id"), "raw": order}
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500]
            raise ProviderError(f"razorpay_order_failed: HTTP {exc.response.status_code}: {detail}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"razorpay_order_failed: {exc}") from exc

    def create_payment_link(self, *, amount: int, idempotency_key: str, meta: dict) -> dict:
        try:
            with self._client() as c:
                r = c.post("/payment_links", json={
                    "amount": amount, "currency": "INR", "accept_partial": False,
                    "reference_id": idempotency_key,
                    "description": meta.get("description", "ReclaimAI recovery"),
                })
                r.raise_for_status()
                link = r.json()
            return {"provider": self.name, "idempotency_key": idempotency_key,
                    "status": "issued", "reference": link.get("id"),
                    "short_url": link.get("short_url"), "raw": link}
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500]
            raise ProviderError(f"razorpay_link_failed: HTTP {exc.response.status_code}: {detail}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"razorpay_link_failed: {exc}") from exc

    def get_payment(self, payment_id: str) -> dict:
        try:
            with self._client() as c:
                r = c.get(f"/payments/{payment_id}")
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"razorpay_get_failed: {exc}") from exc

    def cancel_payment_link(self, payment_link_id: str) -> dict:
        try:
            with self._client() as c:
                r = c.post(f"/payment_links/{payment_link_id}/cancel")
                r.raise_for_status()
                return r.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500]
            raise ProviderError(
                f"razorpay_link_cancel_failed: HTTP {exc.response.status_code}: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"razorpay_link_cancel_failed: {exc}") from exc


class MCPPaymentProvider(PaymentProvider):
    """Razorpay tool provider backed by the local MCP server.

    The agent receives only the typed tools exposed by MCP. Credentials remain
    inside the MCP server process and never enter agent state or prompts.
    """

    name = "razorpay-mcp"

    def _call(self, tool: str, arguments: dict) -> dict:
        from ..mcp.client import call_tool
        try:
            return asyncio.run(call_tool(tool, arguments))
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"razorpay_mcp_{tool}_failed: {exc}") from exc

    def retry_payment(self, *, amount: int, idempotency_key: str, meta: dict) -> dict:
        result = self._call("create_order", {
            "amount": amount, "currency": "INR",
            "receipt": f"reclaim_{idempotency_key[:32]}",
            "notes": {"reclaim_idempotency_key": idempotency_key,
                      "reason": meta.get("reason", "")},
        })
        return {"provider": "razorpay", "status": result.get("status", "created"),
                "reference": result.get("id") or result.get("reference"), "raw": result}

    def create_payment_link(self, *, amount: int, idempotency_key: str, meta: dict) -> dict:
        customer = meta.get("customer", {})
        arguments = {
            "amount": amount, "currency": "INR",
            # Razorpay limits reference_id to 40 characters. The first 32
            # digest characters retain deterministic provider idempotency.
            "reference_id": f"reclaim_{idempotency_key[:32]}",
            "description": meta.get("description", "ReclaimAI recovery"),
            "notify_email": bool(meta.get("notify", True) and customer.get("email")),
            "notify_sms": bool(meta.get("notify", True) and customer.get("contact")),
            "reminder_enable": meta.get("reminder_enable", True),
        }
        for field, value in (("customer_email", customer.get("email")),
                             ("customer_contact", customer.get("contact")),
                             ("customer_name", customer.get("name"))):
            if value:
                arguments[field] = value
        result = self._call("create_payment_link", arguments)
        reference = result.get("id") or result.get("payment_link_id") or result.get("reference")
        notifications = []
        if meta.get("notify", True) and reference:
            for medium, recipient in (("email", customer.get("email")), ("sms", customer.get("contact"))):
                if recipient:
                    notifications.append({"medium": medium, "recipient": recipient,
                                          "result": self._call("payment_link_notify", {
                                              "payment_link_id": reference, "medium": medium})})
        return {"provider": "razorpay", "status": result.get("status", "issued"),
                "reference": reference, "short_url": result.get("short_url"),
                "raw": result, "notifications": notifications}

    def get_payment(self, payment_id: str) -> dict:
        return self._call("fetch_payment", {"payment_id": payment_id})

    def cancel_payment_link(self, payment_link_id: str) -> dict:
        settings = get_settings()
        if not settings.razorpay_key_id or not settings.razorpay_key_secret:
            raise ProviderError("razorpay_link_cancel_failed: credentials are not configured")
        return RazorpayProvider(
            settings.razorpay_key_id, settings.razorpay_key_secret
        ).cancel_payment_link(payment_link_id)


def get_payment_provider(settings: Settings | None = None) -> PaymentProvider:
    settings = settings or get_settings()
    if settings.payment_provider == "razorpay" and settings.razorpay_key_id:
        return MCPPaymentProvider()
    return MockPaymentProvider(settings.mock_payment_success_rate, settings.random_seed)
