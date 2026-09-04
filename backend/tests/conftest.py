# FILE: backend/tests/conftest.py
"""Test fixtures: isolated SQLite DB, seeded config, and an authenticated client.

Tests run with the LOCAL profile (mock payment, rules LLM, local queue). The
`client` fixture uses FastAPI's TestClient which starts the in-process worker via
the app lifespan, so end-to-end async flow is exercised. `drain` waits for the
queue to empty.
"""
from __future__ import annotations

import os
import tempfile

import pytest

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["PAYMENT_PROVIDER"] = "mock"
os.environ["LLM_PROVIDER"] = "rules"
os.environ["QUEUE_PROVIDER"] = "local"

from fastapi.testclient import TestClient  # noqa: E402

from app import db, seed  # noqa: E402
from app.main import app  # noqa: E402
from app.queue import get_queue, reset_queue  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    # Stop any worker/queue from a previous test BEFORE resetting the DB, so no
    # background thread is mid-statement when the connection is closed.
    reset_queue()
    db.reset_db()
    seed.seed_config()
    yield
    reset_queue()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth(client):
    r = client.post("/api/auth/login",
                    json={"email": "owner@example.com", "password": "reclaim123"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def drain(timeout: float = 15.0) -> None:
    get_queue().join(timeout=timeout)
    import time
    time.sleep(0.3)
