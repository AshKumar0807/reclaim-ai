// FILE: frontend/src/pages/Dashboard.jsx
// KPI cards + recovery pipeline + a "simulate payment failure" control that
// drives the whole backend flow (webhook -> queue -> LangGraph -> outcome).
import { useEffect, useState } from "react";
import { api, inr } from "../api";

function Card({ label, value, sub, accent = "text-slate-100" }) {
  return (
    <div className="bg-slate-900 rounded-xl p-4 border border-slate-800">
      <div className="text-slate-400 text-xs uppercase tracking-wide">{label}</div>
      <div className={`text-2xl font-bold mt-1 ${accent}`}>{value}</div>
      {sub && <div className="text-slate-500 text-xs mt-1">{sub}</div>}
    </div>
  );
}

export default function Dashboard({ tick }) {
  const [m, setM] = useState(null);
  const [pipe, setPipe] = useState(null);
  const [recent, setRecent] = useState([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);

  async function refresh() {
    setM(await api.metrics());
    setPipe(await api.pipeline());
    setRecent(await api.recoveries("?limit=6"));
  }
  useEffect(() => { refresh().catch(console.error); }, [tick]);

  async function simulate(kind) {
    setBusy(true);
    setNotice(null);
    try {
      const presets = {
        card: { event: "payment.failed", amount: 500000, failure_reason: "card_expired", risk_type: "payment_failure" },
        funds: { event: "payment.failed", amount: 300000, failure_reason: "insufficient_funds", risk_type: "payment_failure" },
        cart: { event: "payment.failed", amount: 800000, failure_reason: "", risk_type: "checkout_abandonment" },
        b2b: { event: "payment.failed", amount: 10000000, failure_reason: "disputed_invoice", risk_type: "overdue_invoice", days_overdue: 60 },
      };
      const result = await api.simulate(presets[kind]);
      setNotice(`Event accepted: ${result.recovery_event_id || result.status}`);
      setTimeout(() => refresh().catch(() => { }), 1200); // give the async worker a moment
    } catch (e) {
      setNotice(`Could not start recovery: ${e.message}`);
    } finally { setBusy(false); }
  }

  if (!m) return <div className="text-slate-400">Loading…</div>;

  const stages = pipe ? [
    ["Detected", pipe.detected], ["Diagnosed", pipe.diagnosed],
    ["Action Selected", pipe.action_selected], ["Approval Required", pipe.approval_required],
    ["Executed", pipe.executed], ["Escalated", pipe.escalated],
    ["Recovered", pipe.recovered],
  ] : [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">How much revenue was at risk, and how much did we recover?</h2>
        <div className="flex gap-2">
          {[["funds", "Sim: Insufficient funds"], ["card", "Sim: Expired card"],
          ["cart", "Sim: Abandoned cart"], ["b2b", "Sim: High-value B2B"]].map(([k, label]) => (
            <button key={k} disabled={busy} onClick={() => simulate(k)}
              className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs disabled:opacity-50">
              {label}
            </button>
          ))}
        </div>
      </div>
      {notice && <div className="rounded-lg border border-sky-500/30 bg-sky-500/10 px-4 py-3 text-sm text-sky-200">{notice}</div>}

      <div className="grid grid-cols-2 md:grid-cols-6 gap-4">
        <Card label="Revenue at Risk" value={inr(m.revenue_at_risk)} />
        <Card label="Gross Recovered" value={inr(m.gross_recovered)} accent="text-emerald-400" />
        <Card label="Net Recovered" value={inr(m.net_recovered)} accent="text-emerald-400" />
        <Card label="Recovery Rate" value={`${m.recovery_rate}%`} />
        <Card label="Active Recoveries" value={m.active_recoveries} />
        <Card label="Needs Approval" value={m.pending_approvals} accent="text-amber-400" />
      </div>

      <div className="bg-slate-900 rounded-xl p-4 border border-slate-800">
        <div className="font-semibold mb-3">Recovery pipeline</div>
        <div className="flex items-center gap-2 flex-wrap">
          {stages.map(([label, n], i) => (
            <div key={label} className="flex items-center gap-2">
              <div className="bg-slate-800 rounded-lg px-4 py-3 text-center min-w-[120px]">
                <div className="text-xs text-slate-400">{label}</div>
                <div className="text-xl font-bold">{n}</div>
              </div>
              {i < stages.length - 1 && <span className="text-slate-600">→</span>}
            </div>
          ))}
        </div>
      </div>

      <div className="bg-slate-900 rounded-xl p-4 border border-slate-800">
        <div className="font-semibold mb-3">Latest agent decisions</div>
        <div className="space-y-2 text-sm">
          {recent.map((r) => (
            <div key={r.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-slate-800 pt-2 first:border-0 first:pt-0">
              <span className="font-mono text-xs text-slate-500">{r.id}</span>
              <span>{r.selected_action || "waiting for decision"}</span>
              <span className="text-slate-400">{r.root_cause || "diagnosing"}</span>
              <span className="ml-auto text-xs text-slate-300">{r.status}</span>
            </div>
          ))}
          {recent.length === 0 && <div className="text-slate-500 text-sm">No agent decisions yet.</div>}
        </div>
      </div>
    </div>
  );
}
