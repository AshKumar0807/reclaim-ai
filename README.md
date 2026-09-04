# ReclaimAI — Autonomous Revenue Recovery (v2)

> Detect revenue at risk → diagnose → decide a **bounded** intervention → enforce
> **deterministic guardrails** → execute through a **tool interface** → attribute
> the real payment **outcome** → audit everything. Built to the attached
> **API Contract**, **System Architecture & Agent Spec**, and **Product/UI Spec**.

**Core safety invariant (spec 22):** the LLM *recommends*; **policy/guardrails
authorize**; **tools execute**. The model can never move money directly.

```
Razorpay ─payment.failed─▶ FastAPI /webhooks/razorpay
        (verify sig • dedupe • persist) ─▶ RabbitMQ ─▶ Worker ─▶ LangGraph
        detect ▶ diagnose ▶ decide ▶ guardrail ─┬─ ALLOW ─▶ execute ─▶ tool(Mock|Razorpay)
                                                 ├─ REQUIRE_APPROVAL ─▶ human queue
                                                 └─ DENY ─▶ stop/escalate
        outcome (payment.captured) ─▶ PostgreSQL ─▶ Dashboard (SSE live)
```

---

## What’s implemented

| Area | Status |
| --- | --- |
| FastAPI backend, merchant-scoped, JWT auth + RBAC (owner/finance_admin/operator/viewer) | ✅ |
| Razorpay webhook intake: raw body, **HMAC signature verify**, **dedup**, persist, enqueue, return fast | ✅ |
| Async queue (spec 6): `QueueProvider` → **LocalQueue** (threaded, DLQ, retries) + **RabbitMQQueue** (pika) | ✅ |
| **LangGraph workflow** (drop-in engine; real `langgraph` auto-detected) — detect→diagnose→decide→guardrail→execute/approval→outcome | ✅ |
| Bounded action set (SMART_RETRY, PAYMENT_LINK, BOUNDED_COUPON, HINGLISH_NUDGE, B2B_RECEIVABLES_CHASER) | ✅ |
| Deterministic guardrails → ALLOW / DENY / REQUIRE_APPROVAL (LLM can’t override) | ✅ |
| **Idempotency** `sha256(event+attempt+action)` under a UNIQUE constraint | ✅ |
| Human approval queue, **idempotent** (double-approve → HTTP 409, no 2nd action) | ✅ |
| **Outcome attribution** — Executed ≠ Recovered; **natural recovery** via capture webhook | ✅ |
| Graceful **provider failure** → mark FAILED, audit, escalate (worker never crashes) | ✅ |
| Append-only **audit log** + **correlation_id** end-to-end | ✅ |
| Provider abstractions: **Mock** + **Razorpay** payment, LLM (rules/groq), notifier | ✅ |
| React/Vite/Tailwind dashboard on the real API: login, KPIs, pipeline, recoveries+timeline, approvals, audit, settings, **SSE live updates** | ✅ |
| Dockerized: Postgres + RabbitMQ + API + Worker + Frontend | ✅ |
| Tests: 15 passing (dedup, idempotency, guardrails, approval-409, isolation, provider-failure, e2e, natural recovery) | ✅ |

See **IMPLEMENTATION_NOTES.md** for the engineering decisions and the few honest
deltas from a full production build.

---

## Run it — zero infra (simulation mode)

Needs only Python + the packages in `backend/requirements.txt`.

```bash
cd backend
pip install -r requirements.txt
python -m app.seed                       # seed merchant/users/strategies/guardrails/templates
uvicorn app.main:app --reload            # starts API + in-process worker (LOCAL queue)
```

Drive the whole flow (no Razorpay needed):

```bash
# login
TOKEN=$(curl -s localhost:8000/api/auth/login -H 'content-type: application/json' \
  -d '{"email":"owner@example.com","password":"reclaim123"}' | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# simulate a failed payment -> webhook -> queue -> LangGraph -> outcome
curl -s localhost:8000/webhooks/simulate -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"event":"payment.failed","amount":500000,"failure_reason":"insufficient_funds"}'

# watch metrics fill in
curl -s localhost:8000/api/dashboard/metrics -H "authorization: Bearer $TOKEN"
```

Frontend:

```bash
cd frontend
npm install
VITE_API_URL=http://localhost:8000 npm run dev     # http://localhost:5173
# login: owner@example.com / reclaim123 → click the "Sim: …" buttons
```

## Run it — full stack (Postgres + RabbitMQ + API + Worker + Frontend)

```bash
docker compose up --build
# API   http://localhost:8000/docs
# UI    http://localhost:5173
# RabbitMQ mgmt http://localhost:15672 (guest/guest)
```

This runs the **RabbitMQ profile**: the API publishes jobs and the **separate
worker** consumes them (workers scale independently — spec 18).

## Real Razorpay Test Mode

Set in `backend/.env`:

```
PAYMENT_PROVIDER=razorpay
RAZORPAY_KEY_ID=rzp_test_xxx
RAZORPAY_KEY_SECRET=xxx
RAZORPAY_WEBHOOK_SECRET=xxx     # enables real HMAC signature verification
```

Point a Razorpay **test** webhook at `POST /webhooks/razorpay` (payment.failed,
payment.captured, payment_link.paid). Everything else is identical — the
workflow only talks to the `PaymentProvider` interface.

## Live Mode (Razorpay Production)

Live mode uses real Razorpay credentials and can create real payment links or
orders. Configure the backend before starting it:

```bash
cp .env.example backend/.env
# Edit backend/.env:
PAYMENT_PROVIDER=razorpay
RAZORPAY_ENV=production
RAZORPAY_KEY_ID=rzp_live_xxx
RAZORPAY_KEY_SECRET=xxx
RAZORPAY_WEBHOOK_SECRET=xxx
# Optional live diagnosis:
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_xxx
```

Start the full stack with the separate RabbitMQ worker:

```bash
docker compose up --build
```

For local development, add your ngrok token to `backend/.env`:

```env
NGROK_AUTHTOKEN=your_ngrok_authtoken
```

The stack starts an ngrok tunnel to the backend. Open
`http://localhost:4040` or run:

```bash
curl -s http://localhost:4040/api/tunnels
```

Copy the `public_url` beginning with `https://`, then configure the Razorpay
production webhook URL as `<public_url>/webhooks/razorpay` and use the same
webhook secret in `backend/.env`. Verify `http://localhost:8000/health` reports
`"payment_provider":"razorpay"`. Do not use `/webhooks/simulate` for live
validation; send events from Razorpay instead. The current implementation uses
SQLite on the shared Docker volume; PostgreSQL is provisioned but is not yet the
active repository backend (see Implementation Notes).

---

## Verification performed

```bash
cd backend && python -m pytest -q      # 15 passed
```

Covered: webhook **dedup**, idempotency key determinism + **no duplicate
actions**, guardrail ALLOW/DENY/REQUIRE_APPROVAL, high-value → approval queue,
**approve twice → 409**, rejection closes recovery, **merchant isolation** (404 +
empty dashboard for other merchant), **graceful provider-failure escalation**,
end-to-end pipeline + dashboard consistency, **natural recovery** + idempotent
capture. A live end-to-end script also confirms the full funnel, SSE events, and
zero dead-letters.

## Configuration (spec 13)

`PAYMENT_PROVIDER` mock|razorpay · `LLM_PROVIDER` rules|groq ·
`QUEUE_PROVIDER` local|rabbitmq · `DATABASE_URL` sqlite|postgres. Defaults =
LOCAL (zero keys). See `.env.example`.

## Razorpay MCP tool boundary

When `PAYMENT_PROVIDER=razorpay`, the recovery worker connects to Razorpay's
official hosted MCP server at `RAZORPAY_MCP_URL` for each authorized tool call.
The agent can discover and call:

- `create_order` for bounded order creation
- `create_payment_link` for customer-facing recovery links
- `payment_link_notify` for Razorpay-owned email/SMS delivery
- `fetch_payment` for provider status inspection
- `update_payment_link` to disable reminders and schedule replacement links
  to expire

The database idempotency key is created before the MCP call, and guardrails
must allow or approve the action first. The worker sends a Basic merchant token
to the official MCP endpoint; credentials never enter agent state or prompts.
Webhooks remain mandatory: they verify signatures, enqueue
failures, and are the source of truth for captures, paid links, refunds,
disputes, subscription/invoice lifecycle events, and final outcomes.

## Offline agent evaluation

Run the deterministic benchmark from the backend container:

```bash
docker compose exec backend python -m evals.runner
```

The current suite contains 60 cases: 20 normal, 15 edge, and 25 adversarial.
It reports diagnosis accuracy, decision accuracy, safety rate, and policy
latency. It does not call Groq, Razorpay, MCP, or send notifications. Live
provider trajectory metrics must be collected separately from audit records and
MCP/provider request telemetry.
