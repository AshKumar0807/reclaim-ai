# FILE: backend/app/routers/webhooks.py
"""Webhook endpoints (spec 5).

POST /webhooks/razorpay  - real Razorpay webhook intake (signature-verified,
                           deduplicated, persisted, enqueued). Returns quickly.
POST /webhooks/simulate  - authenticated convenience endpoint to drive the whole
                           flow without real Razorpay (simulation mode). Builds a
                           Razorpay-shaped payload and runs the same intake.
"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, Header, Request, Response

from .. import db, webhook_intake
from ..schemas import SimulateWebhookRequest
from ..security import Principal, get_current_user

router = APIRouter(tags=["webhooks"])


def _resolve_merchant_from_webhook(payload: dict) -> str:
    """Resolve which merchant a webhook belongs to. Real Razorpay would map the
    account/webhook to a merchant; for this build we use metadata or the single
    seeded merchant."""
    meta = payload.get("metadata", {}) if isinstance(payload, dict) else {}
    if meta.get("merchant_id"):
        return meta["merchant_id"]
    row = db.query_one("SELECT id FROM merchants ORDER BY created_at ASC LIMIT 1")
    return row["id"] if row else "merchant_001"


@router.post("/webhooks/razorpay")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str | None = Header(default=None),
    x_razorpay_event_id: str | None = Header(default=None),
):
    """Spec 5: read raw body -> verify signature -> dedup -> persist -> enqueue."""
    raw = await request.body()
    try:
        payload = json.loads(raw.decode() or "{}")
    except json.JSONDecodeError:
        return Response(content='{"status":"bad_json"}', status_code=400,
                        media_type="application/json")
    merchant_id = _resolve_merchant_from_webhook(payload)

    # mark last webhook received (onboarding screen surfaces this)
    db.execute("UPDATE merchant_connections SET last_webhook_at=datetime('now'), "
               "webhook_status='active' WHERE merchant_id=?", (merchant_id,))

    result = webhook_intake.process_webhook(raw, x_razorpay_signature, merchant_id,
                                            verify=True, event_id=x_razorpay_event_id)
    return Response(content=json.dumps(result), status_code=result.get("http", 200),
                    media_type="application/json")


@router.post("/webhooks/simulate")
def simulate_webhook(body: SimulateWebhookRequest, user: Principal = Depends(get_current_user)):
    """Drive the full pipeline in simulation mode (no real Razorpay needed)."""
    payment_id = body.payment_id or f"pay_{uuid.uuid4().hex[:10]}"
    order_id = body.order_id or f"order_{uuid.uuid4().hex[:10]}"
    correlation_id = f"corr_{uuid.uuid4().hex[:12]}"
    payload = {
        "id": f"evt_{uuid.uuid4().hex[:12]}",
        "event": body.event,
        "payload": {"payment": {"entity": {
            "id": payment_id, "order_id": order_id, "amount": body.amount,
            "currency": "INR", "error_reason": body.failure_reason,
            "method": "card", "email": body.customer_ref,
        }}},
        "metadata": {"merchant_id": user.merchant_id, "risk_type": body.risk_type,
                     "days_overdue": body.days_overdue, "correlation_id": correlation_id},
    }
    raw = json.dumps(payload).encode()
    db.execute("UPDATE merchant_connections SET last_webhook_at=datetime('now'), "
               "webhook_status='active' WHERE merchant_id=?", (user.merchant_id,))
    return webhook_intake.process_webhook(raw, None, user.merchant_id, verify=False)
