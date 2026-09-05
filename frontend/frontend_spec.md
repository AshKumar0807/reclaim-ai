# ReclaimAI — Frontend Product & UI Specification

## 1. Objective

Transform the existing React/Vite/Tailwind frontend into a polished **Revenue Recovery Control Center** for merchants.

The UI should make three things immediately obvious:

1. **How much revenue is at risk?**
2. **What is the recovery agent currently doing?**
3. **Why did the agent make a particular decision?**

Do not redesign the application into a generic SaaS admin dashboard. The UI should communicate that ReclaimAI is an **active, intelligent revenue-recovery system**.

Reuse the existing frontend architecture, API layer, routes, and components wherever possible.

---

# 2. Visual Theme

## Overall style

Use a modern fintech/SaaS aesthetic:

- Dark primary theme with subtle surfaces/cards.
- Clean typography and strong numeric hierarchy.
- Rounded cards, but avoid excessive "bubble" styling.
- Subtle borders and shadows.
- High information density without feeling cluttered.
- Use animations sparingly for state changes and live activity.
- Avoid excessive gradients, glassmorphism, neon effects, or decorative AI imagery.

The product should feel closer to a **financial operations console** than a chatbot.

## Color semantics

Use color primarily to communicate state:

- Green → recovered/success
- Red → failed/high risk
- Amber → approval/warning
- Blue/indigo → active agent processing
- Gray → inactive/closed
- Purple → AI/agent-related information

Do not use color as the only indicator; pair important states with text/icons.

---

# 3. Global Application Layout

Use a persistent application shell:

```text
┌──────────────────────────────────────────────────────────────┐
│ ReclaimAI                         Merchant ▼   ● Connected    │
├───────────────┬──────────────────────────────────────────────┤
│               │                                              │
│ Dashboard     │                                              │
│ Recoveries    │              MAIN CONTENT                    │
│ Approvals  3  │                                              │
│ Audit         │                                              │
│               │                                              │
│───────────────│                                              │
│ Settings      │                                              │
│               │                                              │
│ ● Razorpay    │                                              │
│   Connected   │                                              │
└───────────────┴──────────────────────────────────────────────┘
```

Sidebar should contain:

- Dashboard
- Recoveries
- Approvals
- Audit
- Settings

Show an approval count badge when approvals are pending.

Bottom of sidebar:

```text
Razorpay
● Connected
Test Mode
```

The connection indicator should reflect the actual backend state.

---

# 4. Dashboard

The dashboard is the most important screen.

It should communicate the product's value within approximately 10 seconds.

## 4.1 Header

Display:

**Good evening, Merchant**

Subtitle:

> Here's what ReclaimAI recovered for you.

Include:

- Current period selector
- Refresh button
- Razorpay connection status

---

# 5. KPI Section

Show five primary metrics.

```text
┌────────────────┐ ┌────────────────┐ ┌────────────────┐
│ Revenue at Risk│ │ Gross Recovered│ │ Recovery Rate  │
│ ₹2,40,000      │ │ ₹1,72,000      │ │ 71.6%          │
│ +12.4%         │ │ +18.2%         │ │ +5.3%          │
└────────────────┘ └────────────────┘ └────────────────┘

┌────────────────┐ ┌────────────────┐
│ Active         │ │ Needs Approval │
│ Recoveries     │ │                │
│ 24             │ │ 7              │
└────────────────┘ └────────────────┘
```

Use actual API data.

Do not fabricate trends if the backend does not provide historical comparison data.

---

# 6. Recovery Summary

Immediately below the KPIs, show a concise narrative:

> **ReclaimAI recovered ₹1.72L from 86 payments this period. ₹68K remains recoverable across 24 active cases.**

The values must come from the API.

This gives the dashboard a clear business narrative rather than just displaying numbers.

---

# 7. Interactive Recovery Pipeline

Create a prominent pipeline visualization.

```text
Failed
 124
  │
  ▼
Diagnosed
 118
  │
  ▼
Recovery Selected
 103
  │
  ▼
Action Taken
 97
  │
  ▼
Recovered
 86
```

Each stage should be clickable.

Clicking a stage filters/navigates to the corresponding recovery cases.

Show additional states where appropriate:

- Awaiting approval
- Escalated
- Blocked by guardrail

Use animated transitions when counts change.

The pipeline should visually communicate:

**Payment failure → Agent reasoning → Recovery action → Revenue recovered**

---

# 8. Agent Activity Feed

Add a live activity panel on the dashboard.

Title:

**Agent Activity**

Example:

```text
● Payment diagnosed
  ₹4,999 · Insufficient funds
  12 seconds ago

● Recovery action executed
  Payment Link · ₹12,500
  28 seconds ago

● Approval required
  ₹75,000 · B2B Receivables Chaser
  1 minute ago

● Guardrail blocked action
  Discount exceeded configured limit
  2 minutes ago
```

Use real audit/recovery events.

If SSE is available, use it.

Otherwise use lightweight polling.

New events should animate into the list subtly.

---

# 9. Recovery Strategy Performance

Add a compact analytics card:

**Recovery Strategies**

Show the distribution of recovery actions:

```text
Payment Link          42%
Smart Retry           28%
Hinglish Nudge        18%
Bounded Coupon         7%
B2B Chaser             5%
```

Below it:

```text
Best performing strategy

Payment Link
₹68,420 recovered
72% success rate
```

Only display metrics that can be derived from the backend.

Make each strategy clickable to filter the Recoveries page.

---

# 10. Recovery Detail

The recovery detail view should be the **main demonstration screen for the agent**.

Clicking a recovery should open a detailed view/modal/page.

Structure it as a timeline.

## Payment

```text
Payment
₹4,999
Failed
```

Show:

- Payment ID
- Order ID
- Payment method
- Amount
- Currency
- Timestamp

---

## Diagnosis

```text
WHY DID IT FAIL?

Insufficient funds

Agent diagnosis:
Recoverable
Confidence: 91%
```

Show structured diagnosis information returned by the backend.

Do not expose private chain-of-thought.

Show only the structured decision rationale intended for the UI.

---

## Decision

```text
AGENT DECISION

Payment Link

Why this action?

Customer can retry without requiring
a discount or manual intervention.
```

Show:

- Selected action
- Reason
- Confidence if available
- Attempt number

---

# 11. Guardrail Visualization

Make guardrails highly visible.

```text
SAFETY CHECK

✓ Amount within autonomous limit
✓ Contact cooldown passed
✓ Customer has not opted out
✓ Discount limit satisfied
✓ Action is idempotent

RESULT

✓ ACTION ALLOWED
```

For blocked actions:

```text
SAFETY CHECK

✓ Customer identified
✓ Contact cooldown passed
✕

Discount limit exceeded

Requested: 18%
Maximum: 10%

ACTION BLOCKED
```

For approval:

```text
SAFETY CHECK

⚠ High-value transaction

₹75,000 exceeds autonomous execution threshold.

HUMAN APPROVAL REQUIRED
```

This should be one of the strongest visual components in the application.

---

# 12. Recovery Action Timeline

Show the actual lifecycle:

```text
Payment Failed
     ↓
Agent Diagnosed
     ↓
Strategy Selected
     ↓
Guardrails Checked
     ↓
Payment Link Generated
     ↓
Customer Notified
     ↓
Payment Captured
     ↓
₹4,999 Recovered
```

Each node should show:

- timestamp
- status
- relevant metadata

Clicking a node can reveal the associated audit event.

---

# 13. Approval Queue

The existing Approvals page should become an operational decision center.

Header:

**Human Approval Required**

Show:

```text
7 actions require your attention
```

Each approval card should include:

```text
₹75,000
B2B customer

Recommended action
Receivables Chaser

Why?
Transaction exceeds autonomous
execution threshold.

Guardrails
✓ Customer verified
✓ Within contact policy
⚠ High-value transaction

[ Approve ] [ Reject ]
```

Approval buttons should produce visible state transitions:

```text
Pending
  ↓
Approved
  ↓
Executing
  ↓
Executed
```

Disable buttons while the request is processing.

Prevent duplicate clicks.

---

# 14. Recoveries Page

Turn the current recovery list into a powerful operational table.

Columns:

- Status
- Customer
- Amount
- Failure reason
- Diagnosis
- Selected action
- Agent status
- Recovery outcome
- Created at

Filters:

- Status
- Failure reason
- Recovery action
- Amount range
- Approval required
- Recovered / Lost / Escalated

Search:

- Customer
- Payment ID
- Order ID

Clicking a row opens the Recovery Detail view.

---

# 15. Audit Page

Make the Audit page feel like an explanation of the agent's behavior.

Example:

```text
09:41:22
PAYMENT_FAILED
₹4,999
       ↓
09:41:22
DIAGNOSIS
Insufficient funds
       ↓
09:41:22
DECISION
Payment Link
       ↓
09:41:22
GUARDRAIL
Allowed
       ↓
09:41:23
ACTION_EXECUTED
Payment Link created
       ↓
09:44:08
PAYMENT_CAPTURED
₹4,999 recovered
```

Allow filtering by:

- Recovery
- Event type
- Action
- Status
- Date

The audit view should demonstrate that every important agent decision is traceable.

---

# 16. Customer Recovery Journey

Within Recovery Detail, add an optional customer journey section.

```text
Customer Journey

10:32
Payment failed
₹4,999

10:32
Agent diagnosed failure

10:32
Payment Link selected

10:33
Customer notified

10:36
Customer opened recovery link

10:37
Payment captured

✓ Revenue recovered
₹4,999
```

This is particularly useful for demos because it converts backend events into a simple business story.

---

# 17. Settings

Keep the existing Settings page, but organize it around merchant configuration.

Sections:

### Merchant

- Merchant name
- Merchant ID
- Account status

### Razorpay

- Connected / disconnected
- Test Mode / Live Mode
- Connection status
- Webhook status

Never expose secret API credentials.

### Recovery Policies

Show configured guardrails in a readable form:

- Autonomous recovery limit
- Maximum discount
- Contact cooldown
- Daily spending/recovery limits
- Approval threshold

These should reflect backend configuration.

### Notifications

Show notification preferences if supported.

---

# 18. Empty States

Every page needs a proper empty state.

Example:

**No approvals required**

> ReclaimAI has no high-risk recovery actions waiting for you.

Do not leave blank tables.

---

# 19. Loading States

Use skeleton loaders rather than blank screens.

For agent processing:

```text
Agent is analyzing payment...

✓ Payment received
✓ Failure diagnosed
● Selecting recovery strategy
○ Checking guardrails
○ Executing action
```

This should be used only when an actual operation is running.

---

# 20. Error States

Errors should explain what happened and what the user can do.

Example:

**Unable to load recoveries**

> The recovery service could not be reached.

[ Retry ]

Never expose stack traces or raw backend errors.

---

# 21. Micro-interactions

Use subtle animation for:

- New recovery arriving
- Recovery changing state
- Approval transition
- Successful recovery
- Guardrail result
- Pipeline count updates

Example successful recovery:

```text
₹4,999
RECOVERED ✓
```

Use a short success animation, but avoid excessive celebration.

---

# 22. Demo Mode

The frontend must work cleanly with the existing simulation/mock backend.

Add a visible but unobtrusive indicator:

```text
● Simulation Mode
```

When using Razorpay Test Mode:

```text
● Razorpay Test Mode
```

Never make the demo appear to be real-money processing when it is not.

---

# 23. Responsive Design

Desktop is the primary target for the buildathon demo.

Still support:

- tablet
- smaller laptop screens

On narrow screens:

- collapse sidebar
- stack KPI cards
- convert large tables into cards
- keep primary actions visible

---

# 24. Technical Requirements

Use the existing:

- React
- Vite
- Tailwind
- API client
- routing structure

Do not introduce unnecessary frontend frameworks.

The frontend should communicate only with the ReclaimAI backend.

```text
React UI
   ↓
ReclaimAI API
   ↓
FastAPI
   ↓
PostgreSQL / Agent / Queue / Razorpay
```

The browser must **never directly access Razorpay credentials or MCP credentials**.

---

# 25. Most Important UX Principle

The application should continuously communicate this story:

```text
PAYMENT FAILURE
       ↓
UNDERSTAND WHY
       ↓
CHOOSE RECOVERY
       ↓
CHECK SAFETY
       ↓
ACT OR ASK HUMAN
       ↓
TRACK OUTCOME
       ↓
RECOVER REVENUE
```

The dashboard is not merely an analytics dashboard.

It is the **control center for an autonomous revenue-recovery agent**.

Every major screen should reinforce one of these questions:

**What money is at risk?**

**What is ReclaimAI doing about it?**

**Why did ReclaimAI make that decision?**

---

# 26. Submission Priority

Prioritize implementation in this order:

### P0 — Must have

1. Dashboard KPI redesign
2. Interactive recovery pipeline
3. Recovery detail with agent decision flow
4. Guardrail visualization
5. Approval queue with live state transitions
6. Recovery table + filtering
7. Audit timeline

### P1 — Strongly recommended

8. Agent activity feed
9. Strategy performance
10. Customer recovery journey
11. Simulation/Test Mode indicator
12. Loading/error/empty states

### P2 — Polish

13. Animations
14. Advanced filtering
15. Responsive improvements
16. Additional analytics

Do not sacrifice functional integration for visual effects.

The final frontend should make the existing ReclaimAI agent easy to understand, demonstrate, and trust.