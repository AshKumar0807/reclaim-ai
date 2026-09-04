# FILE: backend/app/routers/auth.py
"""Auth router (spec 2). POST /api/auth/login -> JWT with user/merchant/role."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from .. import db
from ..schemas import LoginRequest, LoginResponse
from ..security import create_access_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest):
    user = db.query_one("SELECT * FROM users WHERE email = ?", (body.email,))
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    token = create_access_token(user_id=user["id"], merchant_id=user["merchant_id"],
                                role=user["role"])
    return LoginResponse(access_token=token, user_id=user["id"],
                         merchant_id=user["merchant_id"], role=user["role"])
