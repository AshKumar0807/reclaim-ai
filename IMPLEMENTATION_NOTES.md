# Implementation Notes & Engineering Decisions

This document explains how the target architecture was implemented, the
decisions taken, and the **honest deltas** from a full production build — so a
reviewer can see exactly what runs and why.

## What was built (mapping to the specs)

- **Webhook → queue → worker → LangGraph → outcome → dashboard** is implemented
  end-to-end and verified by tests + a live script.
- **LLM recommends / policy authorizes / tools execute** (spec 22) is enforced:
  the decision node can only pick from a config-driven **bounded action set**;
  the **deterministic guardrail engine** returns ALLOW/DENY/REQUIRE_APPROVAL and
  the LLM cannot override it; interventions run only through the
  `PaymentProvider`/`NotificationProvider` interfaces.
- **Merchant isolation** (spec 3): every table is merchant-scoped and every API
  derives `merchant_id` from the JWT (never from the request body). A test
  proves a second merchant sees 404 + an empty dashboard.
- **Idempotency** (spec 12): `sha256(event_id+attempt+action_type)` under a
  UNIQUE constraint; duplicate webhooks are deduped; approvals are idempotent
  (double-approve → HTTP 409, no second financial action).
- **Outcome attribution** (spec 13/14): executing an intervention marks
  `EXECUTED`; a recovery becomes `RECOVERED` only when a capture is matched back
  (post-intervention or **natural recovery**). Status writes are terminal-aware
  so a capture arriving mid-flight is never clobbered.
- **Graceful provider failure** (spec 15): a `ProviderError` is caught, the
  action marked FAILED, `provider_failure` audited, and the event escalated —
  the worker never crashes.

## Key decisions (and why)

### 1. LangGraph-compatible engine instead of the pip package
The sandbox had **no network access to PyPI**, so `langgraph` could not be
installed. Rather than fake a workflow, `app/agent/graph_engine.py` implements a
faithful subset of LangGraph’s public API (`StateGraph`, `add_node`,
`add_edge`, `add_conditional_edges`, `set_entry_point`, `compile`, `invoke`,
`END`). The workflow (`app/agent/workflow.py`) is written against that API, and
`get_state_graph()` will transparently return the **real** `langgraph` if it is
installed — a one-import swap, no node changes. The graph is genuinely
node/edge/conditional-routing based, matching the spec-7 diagram exactly.

### 2. Persistence via stdlib `sqlite3` (Postgres-ready)
SQLAlchemy/psycopg were **not installable** offline. `app/db.py` is a thin
repository over stdlib `sqlite3` (WAL mode, write-lock, dict rows) with an
ANSI-ish schema. Money is stored as **integer paise** for exactness (spec 16).
The docker-compose provisions **PostgreSQL** and shares the SQLite file between
API and worker via a volume so the multi-container RabbitMQ profile runs
end-to-end today. **Delta:** a production Postgres deployment needs a psycopg
implementation of the same repository functions (the SQL is already portable);
this is the one place that is SQLite-specific.

### 3. Queue abstraction: LocalQueue now, RabbitMQ ready
`QueueProvider` has two implementations: a real **threaded in-process
LocalQueue** with bounded retries + a **dead-letter** list (so the async flow
runs with zero infra and is fully testable), and a **RabbitMQQueue** (pika,
durable queue + dead-letter exchange) used when `QUEUE_PROVIDER=rabbitmq`. The
webhook and worker are unaware of which backs them. `pika` is imported lazily so
the LOCAL profile never requires it.

### 4. Auth without passlib/python-jose
PyJWT was available; passlib/jose were not. Passwords use stdlib
**PBKDF2-HMAC-SHA256**; sessions are **HS256 JWTs**. RBAC permissions gate
approvals and Razorpay connect.

### 5. Razorpay via httpx + stdlib HMAC
`RazorpayProvider` uses `httpx` for orders/payment-links and stdlib `hmac` for
webhook **signature verification** — no SDK required (the optional `razorpay`
package can be enabled). In the mock/local profile (no webhook secret),
verification is skipped but the exact intake path (dedup/persist/enqueue) runs.

## Honest deltas / what remains for “full production”

1. **Postgres repository.** Business logic targets the repository API; only the
   `sqlite3` backend is implemented. A psycopg backend (same SQL) is the
   remaining work to run on the provisioned Postgres instead of the shared
   SQLite volume.
2. **Frontend build not run here.** `npm`/registry were offline in the sandbox,
   so `npm run build` wasn’t executed. The React code is standard Vite/Tailwind
   and builds via `npm install && npm run build` (or the frontend Docker image).
3. **Real Razorpay call-outs unverified.** No test credentials were available,
   so the `RazorpayProvider` code path (test-mode orders/links + real signature
   verification) is implemented but exercised only via the mock; wiring is ready
   the moment keys are provided.
4. **SSE fan-out is single-node** (in-process broker). Multi-node needs Redis
   pub/sub or Postgres LISTEN behind the same `publish()` call site.

None of these block the required end-to-end flow in **simulation mode**, which is
implemented, runnable, and tested.
