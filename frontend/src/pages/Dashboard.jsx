import { useEffect, useState } from "react";
import { api, inr } from "../api";

const stageMeta = [
  ["detected", "Failed", "Payment failures received", "bg-rose-500", "text-rose-300"],
  ["diagnosed", "Diagnosed", "Agent understood why", "bg-sky-500", "text-sky-300"],
  ["action_selected", "Strategy selected", "Recovery selected", "bg-violet-500", "text-violet-300"],
  ["executed", "Action taken", "Customer contacted", "bg-amber-500", "text-amber-300"],
  ["recovered", "Recovered", "Revenue captured", "bg-emerald-500", "text-emerald-300"],
];

function Kpi({ label, value, detail, accent = "text-white", icon }) {
  return <div className="panel p-5 min-h-[130px]">
    <div className="flex items-center justify-between text-[11px] uppercase tracking-[.12em] text-slate-500 font-bold">
      <span>{label}</span><span className={`text-base ${accent}`}>{icon}</span>
    </div>
    <div className={`mt-3 text-[28px] leading-none font-extrabold tracking-[-.05em] ${accent}`}>{value}</div>
    {detail && <div className="mt-3 text-xs text-slate-500">{detail}</div>}
  </div>;
}

function timeAgo(value) {
  if (!value) return "Just now";
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

export default function Dashboard({ tick, onNavigate }) {
  const [metrics, setMetrics] = useState(null);
  const [pipeline, setPipeline] = useState(null);
  const [recent, setRecent] = useState([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);
  const [error, setError] = useState(null);

  async function refresh() {
    setError(null);
    const [m, p, r] = await Promise.all([api.metrics(), api.pipeline(), api.recoveries("?limit=5")]);
    setMetrics(m); setPipeline(p); setRecent(r);
  }
  useEffect(() => { refresh().catch(() => setError("Unable to load dashboard data.")); }, [tick]);

  async function simulate(kind) {
    const presets = {
      funds: { event: "payment.failed", amount: 300000, failure_reason: "insufficient_funds", risk_type: "payment_failure" },
      card: { event: "payment.failed", amount: 500000, failure_reason: "card_expired", risk_type: "payment_failure" },
      b2b: { event: "payment.failed", amount: 10000000, failure_reason: "disputed_invoice", risk_type: "overdue_invoice", days_overdue: 60 },
    };
    setBusy(true); setNotice(null);
    try {
      const result = await api.simulate(presets[kind]);
      setNotice(`Recovery event accepted · ${result.recovery_event_id || result.status}`);
      setTimeout(() => refresh().catch(() => {}), 1200);
    } catch { setNotice("Could not start the simulation. Please try again."); }
    finally { setBusy(false); }
  }

  if (error) return <div className="panel p-8 max-w-xl"><div className="text-rose-300 font-bold">Unable to load dashboard</div><p className="text-sm text-slate-400 mt-2">The recovery service could not be reached.</p><button className="mt-5 rounded-lg bg-violet-500 px-4 py-2 text-sm font-bold" onClick={() => refresh().catch(() => setError("Unable to load dashboard data."))}>Retry</button></div>;
  if (!metrics) return <div className="space-y-5"><div className="h-10 w-72 skeleton" /><div className="grid grid-cols-2 lg:grid-cols-5 gap-4">{[1,2,3,4,5].map((n) => <div className="h-32 skeleton" key={n} />)}</div></div>;

  const recoverable = Math.max(0, metrics.revenue_at_risk - metrics.gross_recovered);
  return <div className="space-y-7">
    <div className="flex flex-wrap justify-between gap-5 items-end">
      <div><div className="page-eyebrow">Revenue recovery control center</div><h1 className="page-title mt-2">Good evening, Merchant</h1><p className="text-sm text-slate-400 mt-2">Here’s what ReclaimAI recovered for you.</p></div>
      <div className="flex items-center gap-2"><select className="bg-[#111827] border border-[#29364b] rounded-lg text-xs px-3 py-2 text-slate-300"><option>Current period</option></select><button onClick={() => refresh().catch(() => setError("Unable to refresh dashboard."))} className="border border-[#29364b] rounded-lg px-3 py-2 text-xs text-slate-300 hover:bg-slate-800">↻ Refresh</button></div>
    </div>
    {notice && <div className="rounded-lg border border-violet-500/30 bg-violet-500/10 px-4 py-3 text-sm text-violet-200">{notice}</div>}
    <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
      <Kpi label="Revenue at risk" value={inr(metrics.revenue_at_risk)} detail="Total failed payment value" accent="text-rose-300" icon="↗" />
      <Kpi label="Gross recovered" value={inr(metrics.gross_recovered)} detail="Captured by recovery agent" accent="text-emerald-300" icon="✓" />
      <Kpi label="Recovery rate" value={`${metrics.recovery_rate}%`} detail="Of total revenue at risk" accent="text-violet-300" icon="%" />
      <Kpi label="Active recoveries" value={metrics.active_recoveries} detail="Agent is working now" accent="text-sky-300" icon="●" />
      <Kpi label="Needs approval" value={metrics.pending_approvals} detail="Human decisions pending" accent="text-amber-300" icon="!" />
    </div>
    <div className="panel px-5 py-4 flex flex-wrap gap-2 items-center"><span className="text-sm font-semibold">ReclaimAI recovered <b className="text-emerald-300">{inr(metrics.gross_recovered)}</b> this period.</span><span className="text-sm text-slate-400">{recent.length || "No"} recent cases · <b className="text-slate-200">{inr(recoverable)}</b> remains recoverable across {metrics.active_recoveries} active cases.</span></div>

    <section className="panel p-5">
      <div className="flex flex-wrap justify-between gap-3 mb-5"><div><div className="panel-title">Recovery pipeline</div><p className="text-xs text-slate-500 mt-1">Payment failure → agent reasoning → action → revenue recovered</p></div><button className="text-xs text-violet-300 hover:text-violet-200" onClick={() => onNavigate("Recoveries")}>View all recoveries →</button></div>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {stageMeta.map(([key, label, caption, color, text], index) => <button key={key} onClick={() => onNavigate("Recoveries")} className="text-left group">
          <div className="flex items-center gap-2"><span className={`h-2 w-2 rounded-full ${color}`} /><span className={`text-xs font-semibold ${text}`}>{label}</span>{index < stageMeta.length - 1 && <span className="hidden md:block text-slate-700 ml-auto">→</span>}</div>
          <div className="mt-3 text-2xl font-extrabold">{pipeline?.[key] ?? 0}</div><div className="text-[11px] text-slate-500 mt-1">{caption}</div>
          <div className="h-1 bg-slate-800 rounded-full mt-4 overflow-hidden"><div className={`h-full ${color} rounded-full transition-all`} style={{ width: `${Math.min(100, (pipeline?.[key] || 0) * 5)}%` }} /></div>
        </button>)}
      </div>
    </section>

    <div className="grid lg:grid-cols-[1.35fr_.65fr] gap-5">
      <section className="panel p-5"><div className="flex justify-between items-center mb-4"><div><div className="panel-title">Agent activity</div><p className="text-xs text-slate-500 mt-1">Live decisions from your recovery agent</p></div><span className="text-[11px] text-emerald-300"><span className="status-dot" /> Live</span></div>
        <div className="space-y-1">{recent.map((r) => <button onClick={() => onNavigate("Recoveries")} key={r.id} className="w-full text-left flex items-center gap-3 border-t border-slate-800/80 py-3 first:border-0 hover:bg-slate-900/60 rounded-lg px-2"><span className="h-2 w-2 rounded-full bg-violet-400 shrink-0" /><div className="min-w-0 flex-1"><div className="text-sm font-semibold truncate">{r.selected_action || "Payment diagnosed"}</div><div className="text-xs text-slate-500 mt-1">{inr(r.amount)} · {r.failure_reason || r.root_cause || "Recovery case"}</div></div><span className="text-[11px] text-slate-600">{timeAgo(r.created_at)}</span></button>)}{recent.length === 0 && <div className="py-8 text-center text-sm text-slate-500">No agent activity yet.</div>}</div>
      </section>
      <section className="panel p-5"><div className="panel-title">Simulation controls</div><p className="text-xs text-slate-500 mt-1 mb-5">Test the agent flow without real-money processing.</p><div className="space-y-2">{[["funds","Insufficient funds"],["card","Expired card"],["b2b","High-value B2B"]].map(([key, label]) => <button disabled={busy} onClick={() => simulate(key)} key={key} className="w-full flex items-center justify-between bg-slate-800/60 hover:bg-slate-800 rounded-lg px-3 py-3 text-sm disabled:opacity-50"><span>{label}</span><span className="text-violet-300">Run →</span></button>)}</div></section>
    </div>
  </div>;
}
