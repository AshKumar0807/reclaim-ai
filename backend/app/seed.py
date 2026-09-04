# FILE: backend/app/seed.py
"""Seed merchants, users, strategies, guardrails, templates (+ optional demo
payment/recovery events for a populated dashboard).

Run: python -m app.seed
Idempotent: uses INSERT OR REPLACE / OR IGNORE.
"""
from __future__ import annotations

import json
import uuid

from . import db
from .config import get_settings
from .security import hash_password

MERCHANT_ID = "merchant_001"
DEMO_EMAIL = "owner@example.com"
DEMO_PASSWORD = "reclaim123"

STRATEGIES = [
    ("retry_insufficient_funds", "payment_failure", "insufficient_funds", "SMART_RETRY", {}, 10),
    ("retry_bank_downtime", "payment_failure", "bank_downtime", "SMART_RETRY", {}, 10),
    ("link_expired_card", "payment_failure", "expired_card", "PAYMENT_LINK", {"locale": "en"}, 20),
    ("payment_failure_fallback", "payment_failure", "*", "PAYMENT_LINK", {"locale": "en"}, 90),
    ("sub_link_update", "subscription_failure", "*", "PAYMENT_LINK", {"locale": "en"}, 15),
    ("winback_price", "checkout_abandonment", "price_sensitivity", "BOUNDED_COUPON",
     {"discount_pct": 10, "locale": "hinglish"}, 10),
    ("nudge_distraction", "checkout_abandonment", "distraction_abandonment", "HINGLISH_NUDGE",
     {"channel": "email", "locale": "hinglish"}, 10),
    ("abandon_fallback", "checkout_abandonment", "*", "HINGLISH_NUDGE", {"locale": "en"}, 90),
    ("receivables", "overdue_invoice", "*", "B2B_RECEIVABLES_CHASER",
     {"locale": "en", "promise_days": 7}, 10),
    ("global_nudge", "*", "*", "HINGLISH_NUDGE", {"locale": "en"}, 100),
]

GUARDRAILS = [
    ("maximum_attempts", 3),
    ("high_value_approval_threshold", 5_000_000),  # ₹50,000 paise
    ("max_discount_pct", 15),
    ("daily_spend_cap_inr", 5_000_000),
    ("customer_cooldown_hours", 0),
]

TEMPLATES = [
    ("email", "payment_link", "en", "Complete your payment",
     "Hi {name}, your payment of ₹{amount} didn't go through. Pay securely here: {link}"),
    ("email", "winback_coupon", "hinglish", "Special discount",
     "Hi {name}! Aapka order pending hai. {pct}% discount ke saath sirf ₹{amount}: {link}"),
    ("email", "winback_coupon", "en", "A little something off",
     "Hi {name}, here's {pct}% off — pay just ₹{amount}: {link}"),
    ("email", "nudge", "hinglish", "Aapne kuch chhod diya!",
     "Hi {name}, aapka {item} cart me wait kar raha hai (₹{amount}). Abhi complete karein!"),
    ("email", "nudge", "en", "You left something behind",
     "Hi {name}, your {item} is still in your cart (₹{amount}). Complete it in 2 minutes!"),
    ("email", "receivables_chase", "en", "Invoice reminder",
     "Dear {name}, invoice {invoice} for ₹{amount} is {days} days overdue. Kindly arrange payment."),
]


def seed_config() -> None:
    db.execute("INSERT OR REPLACE INTO merchants (id, name, environment) VALUES (?,?,?)",
               (MERCHANT_ID, "Example Merchant", get_settings().razorpay_env))
    db.execute("INSERT OR IGNORE INTO merchant_connections "
               "(merchant_id, provider, connected, account_ref, webhook_status) "
               "VALUES (?, 'razorpay', 0, ?, 'inactive')",
               (MERCHANT_ID, "acc_XXXXXXXXXXXX1234"))
    db.execute("INSERT OR IGNORE INTO users (id, merchant_id, email, password_hash, role) "
               "VALUES (?,?,?,?, 'owner')",
               (str(uuid.uuid4()), MERCHANT_ID, DEMO_EMAIL, hash_password(DEMO_PASSWORD)))

    db.execute("DELETE FROM strategies WHERE merchant_id = ?", (MERCHANT_ID,))
    for name, rt, rc, action, params, pri in STRATEGIES:
        db.execute("INSERT INTO strategies "
                   "(merchant_id, name, applies_to_risk_type, applies_to_root_cause, "
                   " action_type, params_json, priority, enabled) VALUES (?,?,?,?,?,?,?,1)",
                   (MERCHANT_ID, name, rt, rc, action, json.dumps(params), pri))

    for key, value in GUARDRAILS:
        db.execute("INSERT OR REPLACE INTO guardrails (merchant_id, scope, key, value_json) "
                   "VALUES (?, 'global', ?, ?)",
                   (MERCHANT_ID, key, json.dumps({"value": value})))

    for channel, key, locale, subject, body in TEMPLATES:
        db.execute("INSERT OR REPLACE INTO templates "
                   "(merchant_id, channel, key, locale, subject, body) VALUES (?,?,?,?,?,?)",
                   (MERCHANT_ID, channel, key, locale, subject, body))


def run() -> dict:
    db.init_db()
    seed_config()
    return {"merchant": MERCHANT_ID, "user": DEMO_EMAIL,
            "strategies": len(STRATEGIES), "guardrails": len(GUARDRAILS),
            "templates": len(TEMPLATES)}


if __name__ == "__main__":
    print("Seeding ReclaimAI…")
    print(run())
