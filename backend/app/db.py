# FILE: backend/app/db.py
"""Thin persistence layer over stdlib sqlite3.

Why not SQLAlchemy? This build targets a zero-dependency-install environment, so
we use the standard library. The surface here is a small repository/helper API
(get_conn, query, execute, transaction) plus the full schema. The SQL is kept
ANSI-ish so a psycopg-backed Postgres implementation is a drop-in for prod
(see DESIGN.md). Money is stored as INTEGER PAISE everywhere for exactness
(spec 16: "Money should remain exact").

Concurrency note: SQLite is opened with check_same_thread=False and WAL mode so
the API threadpool + the in-process LocalQueue worker thread can both use it.
A module-level lock serializes writes to avoid 'database is locked'.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager

from .config import get_settings

_settings = get_settings()
_write_lock = threading.RLock()
_conn: sqlite3.Connection | None = None


def _dict_factory(cursor: sqlite3.Cursor, row: tuple) -> dict:
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def get_conn() -> sqlite3.Connection:
    """Return a process-wide sqlite connection (WAL, row->dict)."""
    global _conn
    if _conn is None:
        path = _settings.sqlite_path
        _conn = sqlite3.connect(path, check_same_thread=False)
        _conn.row_factory = _dict_factory
        _conn.execute("PRAGMA journal_mode=WAL;")
        _conn.execute("PRAGMA foreign_keys=ON;")
        _conn.execute("PRAGMA busy_timeout=5000;")
    return _conn


def query(sql: str, params: tuple | dict = ()) -> list[dict]:
    cur = get_conn().execute(sql, params)
    return cur.fetchall()


def query_one(sql: str, params: tuple | dict = ()) -> dict | None:
    cur = get_conn().execute(sql, params)
    return cur.fetchone()


def execute(sql: str, params: tuple | dict = ()) -> int:
    """Execute a write; returns lastrowid. Serialized by a write lock."""
    with _write_lock:
        conn = get_conn()
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Atomic multi-statement transaction guarded by the write lock."""
    with _write_lock:
        conn = get_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


# --------------------------------------------------------------------------- #
# Schema (spec 16 core entities, all merchant-scoped where applicable)
# --------------------------------------------------------------------------- #
SCHEMA = """
CREATE TABLE IF NOT EXISTS merchants (
    id              TEXT PRIMARY KEY,          -- merchant_001
    name            TEXT NOT NULL,
    environment     TEXT NOT NULL DEFAULT 'test',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS merchant_connections (
    merchant_id     TEXT PRIMARY KEY REFERENCES merchants(id),
    provider        TEXT NOT NULL DEFAULT 'razorpay',
    connected       INTEGER NOT NULL DEFAULT 0,   -- boolean
    account_ref     TEXT,                          -- masked externally
    webhook_status  TEXT NOT NULL DEFAULT 'inactive',
    last_webhook_at TEXT,
    -- Secrets are stored server-side only and NEVER returned by any API.
    key_id_enc      TEXT,
    key_secret_enc  TEXT,
    webhook_secret_enc TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    merchant_id     TEXT NOT NULL REFERENCES merchants(id),
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'owner', -- owner|finance_admin|operator|viewer
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS payment_events (
    id              TEXT PRIMARY KEY,             -- provider event id (dedup key)
    merchant_id     TEXT NOT NULL REFERENCES merchants(id),
    payment_id      TEXT,
    order_id        TEXT,
    event_type      TEXT NOT NULL,               -- payment.failed | payment.captured | ...
    amount          INTEGER NOT NULL DEFAULT 0,  -- paise
    currency        TEXT NOT NULL DEFAULT 'INR',
    failure_reason  TEXT,
    method          TEXT,
    customer_ref    TEXT,
    raw_json        TEXT,
    correlation_id  TEXT,
    received_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS recovery_events (
    id              TEXT PRIMARY KEY,            -- rec_...
    merchant_id     TEXT NOT NULL REFERENCES merchants(id),
    payment_event_id TEXT REFERENCES payment_events(id),
    payment_id      TEXT,
    order_id        TEXT,
    amount          INTEGER NOT NULL DEFAULT 0,  -- paise at risk
    currency        TEXT NOT NULL DEFAULT 'INR',
    failure_reason  TEXT,
    customer_ref    TEXT,
    risk            TEXT DEFAULT 'medium',       -- low|medium|high
    meta_json       TEXT NOT NULL DEFAULT '{}',   -- risk_type, days_overdue, etc.
    status          TEXT NOT NULL DEFAULT 'DETECTED',
    diagnosis       TEXT,
    root_cause      TEXT,
    selected_action TEXT,
    attempts        INTEGER NOT NULL DEFAULT 0,
    recovered_amount INTEGER NOT NULL DEFAULT 0, -- paise
    cost_amount     INTEGER NOT NULL DEFAULT 0,  -- paise
    correlation_id  TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at     TEXT
);

CREATE TABLE IF NOT EXISTS recovery_actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id     TEXT NOT NULL REFERENCES merchants(id),
    recovery_event_id TEXT NOT NULL REFERENCES recovery_events(id),
    action_type     TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,        -- sha256(event+attempt+action)
    status          TEXT NOT NULL DEFAULT 'planned', -- planned|pending_approval|executed|failed|skipped
    requires_approval INTEGER NOT NULL DEFAULT 0,
    rationale       TEXT DEFAULT '',
    provider_reference TEXT,
    provider_response TEXT,
    recovered_amount INTEGER NOT NULL DEFAULT 0,
    cost_amount     INTEGER NOT NULL DEFAULT 0,
    correlation_id  TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    executed_at     TEXT
);

CREATE TABLE IF NOT EXISTS approvals (
    id              TEXT PRIMARY KEY,            -- appr_...
    merchant_id     TEXT NOT NULL REFERENCES merchants(id),
    recovery_event_id TEXT NOT NULL REFERENCES recovery_events(id),
    action_id       INTEGER REFERENCES recovery_actions(id),
    status          TEXT NOT NULL DEFAULT 'pending', -- pending|approved|rejected
    reason          TEXT,
    decided_by      TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    decided_at      TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id     TEXT,
    recovery_event_id TEXT,
    payment_id      TEXT,
    entity_type     TEXT NOT NULL,
    entity_id       TEXT NOT NULL,
    actor           TEXT NOT NULL,               -- agent | system | human:<email>
    action          TEXT NOT NULL,
    event_type      TEXT,                        -- recovery.detected, ...
    rationale       TEXT DEFAULT '',
    before_json     TEXT,
    after_json      TEXT,
    correlation_id  TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS strategies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id     TEXT NOT NULL REFERENCES merchants(id),
    name            TEXT NOT NULL,
    applies_to_risk_type TEXT NOT NULL,          -- or '*'
    applies_to_root_cause TEXT NOT NULL DEFAULT '*',
    action_type     TEXT NOT NULL,
    params_json     TEXT NOT NULL DEFAULT '{}',
    priority        INTEGER NOT NULL DEFAULT 100,
    enabled         INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS guardrails (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id     TEXT NOT NULL REFERENCES merchants(id),
    scope           TEXT NOT NULL DEFAULT 'global',
    key             TEXT NOT NULL,
    value_json      TEXT NOT NULL,
    UNIQUE(merchant_id, scope, key)
);

CREATE TABLE IF NOT EXISTS templates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id     TEXT NOT NULL REFERENCES merchants(id),
    channel         TEXT NOT NULL,
    key             TEXT NOT NULL,
    locale          TEXT NOT NULL DEFAULT 'en',
    subject         TEXT DEFAULT '',
    body            TEXT NOT NULL,
    UNIQUE(merchant_id, channel, key, locale)
);

CREATE TABLE IF NOT EXISTS processed_webhooks (
    event_id        TEXT PRIMARY KEY,            -- dedup of duplicate webhooks
    merchant_id     TEXT,
    received_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_rec_merchant_status ON recovery_events(merchant_id, status);
CREATE INDEX IF NOT EXISTS ix_actions_event ON recovery_actions(recovery_event_id);
CREATE INDEX IF NOT EXISTS ix_audit_merchant ON audit_log(merchant_id, recovery_event_id);
CREATE INDEX IF NOT EXISTS ix_payment_ref ON payment_events(payment_id);
"""


def init_db() -> None:
    """Create all tables (idempotent)."""
    with _write_lock:
        conn = get_conn()
        conn.executescript(SCHEMA)
        conn.commit()


def reset_db() -> None:
    """Drop the SQLite file and recreate (used by tests / fresh seed)."""
    global _conn
    with _write_lock:
        if _conn is not None:
            _conn.close()
            _conn = None
        path = _settings.sqlite_path
        for suffix in ("", "-wal", "-shm"):
            p = path + suffix
            if os.path.exists(p):
                os.remove(p)
    init_db()
