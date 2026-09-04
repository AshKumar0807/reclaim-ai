# FILE: backend/app/schemas.py
"""Pydantic API models (request/response bodies)."""
from __future__ import annotations

from pydantic import BaseModel


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    merchant_id: str
    role: str


class MerchantOut(BaseModel):
    merchant_id: str
    name: str
    razorpay_connected: bool
    environment: str
    webhook_status: str


class DashboardMetrics(BaseModel):
    revenue_at_risk: int      # paise
    gross_recovered: int
    net_recovered: int
    recovery_rate: float
    active_recoveries: int
    pending_approvals: int


class ApprovalDecision(BaseModel):
    note: str = ""


class SimulateWebhookRequest(BaseModel):
    """Convenience endpoint to drive the flow without real Razorpay."""
    event: str = "payment.failed"
    amount: int = 500000                 # paise (₹5,000)
    failure_reason: str = "insufficient_funds"
    risk_type: str = "payment_failure"
    payment_id: str | None = None
    order_id: str | None = None
    customer_ref: str = "customer@example.com"
    days_overdue: int = 0
