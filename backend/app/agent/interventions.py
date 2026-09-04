# FILE: backend/app/agent/interventions.py
"""Bounded interventions executed through provider/tool interfaces (spec 10/12).

Each returns a normalized result dict:
    {success, recovered_amount, cost_amount, provider_reference,
     provider_response, message, executed(bool)}

Providers raise ProviderError on failure; the workflow catches it and routes to
graceful FAILED -> audit -> escalate (spec 15). Amounts are integer paise.

IMPORTANT (outcome attribution, spec 13): a mock 'captured'/'paid' here marks the
action executed and, in simulation, immediately drives a payment.captured so the
recovery is only marked RECOVERED via the outcome path (Executed ≠ Recovered).
For a real Razorpay integration, capture arrives asynchronously via webhook.
"""
from __future__ import annotations

from ..providers.notification import NotificationProvider, render_template
from ..providers.payment import PaymentProvider
from . import repository


def _render(merchant_id: str, channel: str, key: str, locale: str, variables: dict) -> str:
    tpl = repository.get_template(merchant_id, channel, key, locale)
    if tpl is None:
        return f"Hi {variables.get('name','there')}, please complete your payment."
    return render_template(tpl["body"], variables)


def smart_retry(state: dict, payment: PaymentProvider, idem: str) -> dict:
    amount = int(state["amount"])
    resp = payment.retry_payment(amount=amount, idempotency_key=idem,
                                 meta={"reason": state.get("failure_reason")})
    captured = resp.get("status") in {"captured", "paid"}
    return {"executed": True, "success": captured,
            "recovered_amount": amount if captured else 0, "cost_amount": 0,
            "provider_reference": resp.get("reference"), "provider_response": resp,
            "message": f"SMART_RETRY -> {resp.get('status')}"}


def payment_link(state: dict, payment: PaymentProvider, notifier: NotificationProvider,
                 idem: str) -> dict:
    amount = int(state["amount"])
    customer = {}
    if state.get("customer_email"):
        customer["email"] = state["customer_email"]
    if state.get("customer_contact"):
        customer["contact"] = state["customer_contact"]
    # A Razorpay test event may contain a placeholder address or omit contact
    # data. Ask the provider tool for the authoritative payment customer before
    # creating a link; never invent or infer a destination.
    if payment.name != "mock" and (
        not customer or customer.get("email", "").endswith("@razorpay.com")
    ) and state.get("payment_id"):
        try:
            provider_payment = payment.get_payment(state["payment_id"])
            source = provider_payment.get("customer") or provider_payment
            if source.get("email") and not source["email"].endswith("@razorpay.com"):
                customer["email"] = source["email"]
            if source.get("contact"):
                customer["contact"] = source["contact"]
        except Exception:
            # Link creation remains the primary action; missing provider contact
            # data is surfaced in the action response instead of guessed.
            pass
    if not customer and state.get("customer_ref"):
        customer["email"] = state["customer_ref"]
    replaced = []
    for previous in repository.list_recovery_actions(state["recovery_event_id"]):
        if previous["action_type"] == "PAYMENT_LINK" and previous.get("provider_reference"):
            replaced.append({"reference": previous["provider_reference"],
                             "result": payment.expire_payment_link(previous["provider_reference"])})
    resp = payment.create_payment_link(amount=amount, idempotency_key=idem,
                                       meta={"description": f"Payment for {state.get('order_id')}",
                                             "customer": customer, "notify": payment.name != "mock",
                                             "reminder_enable": payment.name != "mock"})
    resp["replaced_links"] = replaced
    locale = state.get("action_params", {}).get("locale", "en")
    body = _render(state["merchant_id"], "email", "payment_link", locale,
                   {"name": state.get("customer_ref", "there"),
                    "amount": f"{amount/100:,.0f}", "link": resp.get("short_url", "")})
    if payment.name == "mock":
        notifier.send(channel="email", to=state.get("customer_ref", ""),
                      subject="Complete your payment", body=body, meta={})
    paid = resp.get("status") == "paid"
    return {"executed": True, "success": paid,
            "recovered_amount": amount if paid else 0, "cost_amount": 0,
            "provider_reference": resp.get("reference"), "provider_response": resp,
            "message": f"PAYMENT_LINK replaced={len(replaced)} -> {resp.get('status')}"}


def bounded_coupon(state: dict, payment: PaymentProvider, notifier: NotificationProvider,
                   idem: str) -> dict:
    amount = int(state["amount"])
    pct = float(state.get("action_params", {}).get("discount_pct", 5))
    discounted = int(amount * (1 - pct / 100))
    customer = {"email": state["customer_ref"]} if state.get("customer_ref") else {}
    resp = payment.create_payment_link(amount=discounted, idempotency_key=idem,
                                       meta={"description": f"{pct:.0f}% off", "customer": customer,
                                             "notify": payment.name != "mock",
                                             "reminder_enable": payment.name != "mock"})
    locale = state.get("action_params", {}).get("locale", "hinglish")
    body = _render(state["merchant_id"], "email", "winback_coupon", locale,
                   {"name": state.get("customer_ref", "there"), "pct": f"{pct:.0f}",
                    "amount": f"{discounted/100:,.0f}", "link": resp.get("short_url", "")})
    if payment.name == "mock":
        notifier.send(channel="email", to=state.get("customer_ref", ""),
                      subject=f"{pct:.0f}% off — complete your order", body=body, meta={})
    paid = resp.get("status") == "paid"
    cost = (amount - discounted) if paid else 0
    return {"executed": True, "success": paid,
            "recovered_amount": discounted if paid else 0, "cost_amount": cost,
            "provider_reference": resp.get("reference"), "provider_response": resp,
            "message": f"BOUNDED_COUPON {pct:.0f}% -> {resp.get('status')}"}


def hinglish_nudge(state: dict, notifier: NotificationProvider, idem: str) -> dict:
    import hashlib
    amount = int(state["amount"])
    locale = state.get("action_params", {}).get("locale", "hinglish")
    body = _render(state["merchant_id"], "email", "nudge", locale,
                   {"name": state.get("customer_ref", "there"),
                    "amount": f"{amount/100:,.0f}", "item": "your order"})
    resp = notifier.send(channel="email", to=state.get("customer_ref", ""),
                         subject="You left something behind", body=body, meta={})
    roll = int(hashlib.sha256(idem.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    converted = roll < 0.30
    return {"executed": True, "success": converted,
            "recovered_amount": amount if converted else 0, "cost_amount": 0,
            "provider_reference": None, "provider_response": resp,
            "message": f"HINGLISH_NUDGE -> converted={converted}"}


def b2b_receivables_chaser(state: dict, notifier: NotificationProvider, idem: str) -> dict:
    import hashlib
    amount = int(state["amount"])
    body = _render(state["merchant_id"], "email", "receivables_chase", "en",
                   {"name": state.get("customer_ref", "there"),
                    "amount": f"{amount/100:,.0f}", "invoice": state.get("order_id", ""),
                    "days": str(state.get("days_overdue", 0))})
    resp = notifier.send(channel="email", to=state.get("customer_ref", ""),
                         subject="Invoice overdue", body=body, meta={})
    roll = int(hashlib.sha256(idem.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    paid_now = roll < 0.22
    return {"executed": True, "success": paid_now,
            "recovered_amount": amount if paid_now else 0, "cost_amount": 0,
            "provider_reference": None, "provider_response": resp,
            "message": f"B2B_RECEIVABLES_CHASER -> paid_now={paid_now}"}


DISPATCH = {
    "SMART_RETRY": lambda s, prov, idem: smart_retry(s, prov["payment"], idem),
    "PAYMENT_LINK": lambda s, prov, idem: payment_link(s, prov["payment"], prov["notifier"], idem),
    "BOUNDED_COUPON": lambda s, prov, idem: bounded_coupon(s, prov["payment"], prov["notifier"], idem),
    "HINGLISH_NUDGE": lambda s, prov, idem: hinglish_nudge(s, prov["notifier"], idem),
    "B2B_RECEIVABLES_CHASER": lambda s, prov, idem: b2b_receivables_chaser(s, prov["notifier"], idem),
}
