# FILE: backend/app/main.py
"""FastAPI application entrypoint.

Wires routers, CORS (for the Vite dashboard), structured logging, DB init +
seed, and starts the in-process worker for the LOCAL queue profile so the whole
flow runs from a single `uvicorn app.main:app`. For the RabbitMQ profile you run
the standalone worker.py process instead (workers scale independently, spec 18).
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db, seed
from .config import get_settings
from .jobs import start_worker
from .logging_config import configure_logging, get_logger
from .routers import (
    approvals,
    audit,
    auth,
    dashboard,
    merchant,
    recoveries,
    stream,
    webhooks,
)

logger = get_logger("reclaimai.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging()
    db.init_db()
    # Seed config on first boot (idempotent).
    if not db.query_one("SELECT id FROM merchants LIMIT 1"):
        logger.info("seeding", extra={"ctx_summary": str(seed.run())})
    # Start in-process worker for LOCAL queue (RabbitMQ uses standalone worker).
    if settings.queue_provider == "local":
        start_worker()
        logger.info("inprocess_worker_started")
    logger.info("startup_complete", extra={"ctx_env": settings.environment})
    yield


app = FastAPI(title="ReclaimAI", version="2.0.0",
              description="Autonomous revenue recovery: webhook → queue → LangGraph → recover.",
              lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

for r in (auth.router, merchant.router, dashboard.router, recoveries.router,
          approvals.router, audit.router, webhooks.router, stream.router):
    app.include_router(r)


@app.get("/health", tags=["system"])
def health():
    s = get_settings()
    return {"status": "ok", "app": s.app_name, "environment": s.environment,
            "payment_provider": s.payment_provider, "llm_provider": s.llm_provider,
            "queue_provider": s.queue_provider}


@app.get("/", tags=["system"])
def root():
    return {"name": "ReclaimAI", "docs": "/docs", "health": "/health"}
