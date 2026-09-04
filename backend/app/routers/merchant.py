# FILE: backend/app/routers/merchant.py
"""Merchant + Razorpay connection (spec 3/4). Credentials are NEVER returned."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..config import get_settings
from ..schemas import MerchantOut
from ..security import Principal, get_current_user

router = APIRouter(prefix="/api/merchant", tags=["merchant"])


def _mask(ref: str | None) -> str:
    if not ref:
        return "••••"
    return "•" * max(0, len(ref) - 4) + ref[-4:]


@router.get("", response_model=MerchantOut)
def get_merchant(user: Principal = Depends(get_current_user)):
    m = db.query_one("SELECT * FROM merchants WHERE id = ?", (user.merchant_id,))
    conn = db.query_one("SELECT * FROM merchant_connections WHERE merchant_id = ?",
                        (user.merchant_id,))
    if not m:
        raise HTTPException(404, "Merchant not found")
    return MerchantOut(
        merchant_id=m["id"], name=m["name"],
        razorpay_connected=bool(conn and conn["connected"]),
        environment=m["environment"],
        webhook_status=(conn["webhook_status"] if conn else "inactive"),
    )


@router.post("/razorpay/connect")
def connect_razorpay(user: Principal = Depends(get_current_user)):
    """Starts/confirms the Razorpay connection. In test/local this flips the flag
    and activates the webhook relationship. Secrets stay server-side only."""
    user.require("connect")
    s = get_settings()
    db.execute(
        "UPDATE merchant_connections SET connected=1, webhook_status='active', "
        "key_id_enc=?, key_secret_enc=?, webhook_secret_enc=? WHERE merchant_id=?",
        (s.razorpay_key_id or "test_key_id", s.razorpay_key_secret or "test_secret",
         s.razorpay_webhook_secret or "", user.merchant_id),
    )
    conn = db.query_one("SELECT account_ref FROM merchant_connections WHERE merchant_id=?",
                        (user.merchant_id,))
    return {"connected": True, "environment": s.razorpay_env,
            "merchant_id_masked": _mask(conn["account_ref"] if conn else None)}


@router.get("/razorpay/status")
def razorpay_status(user: Principal = Depends(get_current_user)):
    conn = db.query_one("SELECT connected, webhook_status, last_webhook_at, account_ref "
                        "FROM merchant_connections WHERE merchant_id=?", (user.merchant_id,))
    if not conn:
        return {"connected": False, "webhook_status": "inactive"}
    return {"connected": bool(conn["connected"]), "webhook_status": conn["webhook_status"],
            "last_webhook_at": conn["last_webhook_at"],
            "account_ref_masked": _mask(conn["account_ref"])}


@router.post("/razorpay/disconnect")
def disconnect_razorpay(user: Principal = Depends(get_current_user)):
    user.require("connect")
    db.execute("UPDATE merchant_connections SET connected=0, webhook_status='inactive', "
               "key_id_enc=NULL, key_secret_enc=NULL, webhook_secret_enc=NULL WHERE merchant_id=?",
               (user.merchant_id,))
    return {"connected": False}
