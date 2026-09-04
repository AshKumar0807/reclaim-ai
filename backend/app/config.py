# FILE: backend/app/config.py
"""Central configuration (12-factor).

Defaults are the spec's LOCAL profile so the whole system runs with ZERO
external services and ZERO credentials:

    PAYMENT_PROVIDER=mock  LLM_PROVIDER=rules  QUEUE_PROVIDER=local

Flip individual env vars to move toward Test Mode / Production without code
changes (spec section 13 / 18).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "ReclaimAI"
    environment: str = "local"  # local | test | production

    # ----- Database -----
    # Default: zero-infra SQLite (stdlib sqlite3). In prod point at Postgres and
    # use the psycopg-backed repository (documented in DESIGN); the SQL is ANSI.
    database_url: str = "sqlite:///./reclaimai.db"

    # ----- Providers (spec 12/17) -----
    payment_provider: Literal["mock", "razorpay"] = "mock"
    llm_provider: Literal["rules", "groq"] = "rules"
    notifier_provider: Literal["console", "smtp"] = "console"

    # ----- Queue (spec 6) -----
    queue_provider: Literal["local", "rabbitmq"] = "local"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    queue_name: str = "reclaimai.recovery"
    dlq_name: str = "reclaimai.recovery.dlq"
    max_job_retries: int = 3

    # ----- Razorpay (test mode) -----
    razorpay_env: Literal["test", "production"] = "test"
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    razorpay_webhook_secret: str | None = None  # for signature verification
    razorpay_mcp_url: str = "https://mcp.razorpay.com/mcp"
    mock_payment_success_rate: float = 0.5

    # ----- LLM keys -----
    groq_api_key: str | None = None
    llm_model: str = "llama-3.1-8b-instant"
    llm_timeout_seconds: float = 8.0

    # ----- Auth (spec 4) -----
    jwt_secret: str = "dev-secret-change-me-please-32byte-minimum!!"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720

    # ----- Determinism -----
    random_seed: int = 1729

    @property
    def sqlite_path(self) -> str:
        """Filesystem path parsed from a sqlite:/// URL."""
        if self.database_url.startswith("sqlite:///"):
            return self.database_url.replace("sqlite:///", "", 1)
        return "./reclaimai.db"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
