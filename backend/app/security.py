# FILE: backend/app/security.py
"""Authentication & authorization (spec 4).

- Passwords hashed with stdlib PBKDF2-HMAC-SHA256 (no external passlib needed).
- Sessions are HS256 JWTs (PyJWT) carrying user_id, merchant_id, role.
- get_current_user is the FastAPI dependency that makes EVERY request
  merchant-scoped: downstream code trusts principal.merchant_id, never a
  merchant_id from the client body/query (merchant isolation, spec 3).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_settings

settings = get_settings()
_bearer = HTTPBearer(auto_error=False)

# Role -> permissions (spec 13). Approvals need finance_admin/owner.
ROLE_PERMISSIONS = {
    "owner": {"view", "approve", "configure", "connect"},
    "finance_admin": {"view", "approve", "configure"},
    "operator": {"view", "approve"},
    "viewer": {"view"},
}


# --------------------------------------------------------------------------- #
# Password hashing (PBKDF2, stdlib)
# --------------------------------------------------------------------------- #
def hash_password(password: str, *, iterations: int = 200_000) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _algo, iters, salt, digest = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(dk.hex(), digest)
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# JWT sessions
# --------------------------------------------------------------------------- #
def create_access_token(*, user_id: str, merchant_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "merchant_id": merchant_id,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


@dataclass
class Principal:
    user_id: str
    merchant_id: str
    role: str

    @property
    def permissions(self) -> set[str]:
        return ROLE_PERMISSIONS.get(self.role, set())

    def require(self, permission: str) -> None:
        if permission not in self.permissions:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                f"Role '{self.role}' lacks '{permission}' permission")


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    """Decode the bearer token into a merchant-scoped Principal."""
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    try:
        data = jwt.decode(creds.credentials, settings.jwt_secret,
                          algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {exc}") from exc
    return Principal(user_id=data["sub"], merchant_id=data["merchant_id"], role=data["role"])
