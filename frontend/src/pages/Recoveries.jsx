// FILE: frontend/src/pages/Recoveries.jsx
// Revenue-at-risk table + event detail modal with the full audit timeline.
import { useEffect, useState } from "react";
import { api, inr } from "../api";

const STATUS_COLORS = {
  RECOVERED: "bg-emerald-500/20 text-emerald-300",
  APPROVAL_REQUIRED: "bg-amber-500/20 text-amber-300",
  ESCALATED: "bg-orange-500/20 text-orange-300",
  EXECUTED: "bg-sky-500/20 text-sky-300",
  CLOSED_LOST: "bg-rose-500/20 text-rose-300",
};

function Detail({ id, onClose }) {
  const [d, setD] = useState(null);
  useEffect(() => { api.recovery(id).then(setD).catch(console.error); }, [id]);
  if (!d) return null;
  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center p-4 z-50" onClick={onClose}>
      <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-2xl w-full max-h-[85vh] overflow-auto"
        onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-3 border-b border-slate-800 flex justify-between">
          <h3 className="font-semibold">Recovery {id}</h3>
          <button onClick={onClose} className="text-slate-400">✕</button>
        </div>
        <div className="p-5 space-y-4 text-sm">
          <section>
            <div className="text-xs uppercase text-slate-500 mb-1">Payment</div>
            <div>{d.payment.payment_id} · {inr(d.payment.amount)} · {d.payment.failure_reason}</div>
          </section>
          <section>
            <div className="text-xs uppercase text-slate-500 mb-1">Agent decision</div>
            <div>Diagnosis: {d.diagnosis || "—"}</div>
            <div>Root cause: {d.root_cause || "—"} · Action: <b>{d.decision || "—"}</b></div>
            {Object.keys(d.meta?.failure_context || {}).length > 0 && (
              <div className="mt-2 rounded-lg bg-slate-800/70 p-3 text-xs text-slate-300">
                <div className="text-slate-500 uppercase mb-1">Gateway evidence used</div>
                {Object.entries(d.meta.failure_context).map(([key, value]) => (
                  <div key={key}><span className="text-slate-500">{key}:</span> {value}</div>
                ))}
              </div>
            )}
          </section>
          <section>
            <div className="text-xs uppercase text-slate-500 mb-1">Outcome</div>
            <div>Status: <b>{d.status}</b> · Recovered {inr(d.outcome.recovered_amount)} ·
              Net {inr(d.outcome.net_recovered)}</div>
          </section>
          <section>
            <div className="text-xs uppercase text-slate-500 mb-2">Agent actions</div>
            <div className="space-y-1">
              {d.actions.map((a) => (
                <div key={a.id} className="border border-slate-800 rounded-lg px-3 py-2">
                  <div className="flex justify-between gap-3"><b>{a.action_type}</b><span>{a.status}</span></div>
                  <div className="text-xs text-slate-400 mt-1">{a.rationale || "No rationale recorded."}</div>
                  {(() => {
                    let response = {};
                    try { response = JSON.parse(a.provider_response || "{}"); } catch { }
                    return response.short_url ? (
                      <div className="mt-2 space-y-1">
                        <a className="inline-block text-sky-300 underline" href={response.short_url} target="_blank" rel="noreferrer">
                          Open payment link
                        </a>
                        {response.notifications?.map((n) => (
                          <div key={n.medium} className="text-xs text-slate-400">
                            Razorpay {n.medium} notification sent to {n.recipient}
                          </div>
                        ))}
                      </div>
                    ) : null;
                  })()}
                </div>
              ))}
              {d.actions.length === 0 && <div className="text-slate-500">No action recorded.</div>}
            </div>
          </section>
          {d.approvals.length > 0 && <section>
            <div className="text-xs uppercase text-slate-500 mb-1">Human authorization</div>
            {d.approvals.map((a) => <div key={a.id}>{a.status} · {a.reason}</div>)}
          </section>}
          <section>
            <div className="text-xs uppercase text-slate-500 mb-2">Audit timeline</div>
            <ol className="space-y-1">
              {d.audit_timeline.map((a, i) => (
                <li key={i} className="flex gap-3">
                  <span className="text-slate-500 text-xs w-36">{a.created_at}</span>
                  <span className="font-medium">{a.action}</span>
                  <span className="text-slate-400">{a.rationale}</span>
                </li>
              ))}
            </ol>
          </section>
        </div>
      </div>
    </div>
  );
}

export default function Recoveries({ tick }) {
  const [rows, setRows] = useState([]);
  const [sel, setSel] = useState(null);
  const [filter, setFilter] = useState("");
  useEffect(() => {
    api.recoveries(filter ? `?status=${filter}` : "").then(setRows).catch(console.error);
  }, [tick, filter]);

  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        {["", "RECOVERED", "EXECUTED", "APPROVAL_REQUIRED", "ESCALATED", "CLOSED_LOST"].map((s) => (
          <button key={s} onClick={() => setFilter(s)}
            className={`px-3 py-1 rounded text-xs ${filter === s ? "bg-emerald-500 text-slate-900" : "bg-slate-800"}`}>
            {s || "All"}
          </button>
        ))}
      </div>
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="text-slate-400 text-xs">
            <tr>
              <th className="text-left px-4 py-2">Payment</th>
              <th className="text-right px-4 py-2">Amount</th>
              <th className="text-left px-4 py-2">Failure</th>
              <th className="text-left px-4 py-2">Action</th>
              <th className="text-left px-4 py-2">Status</th>
              <th className="text-right px-4 py-2">Recovered</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} onClick={() => setSel(r.id)}
                className="border-t border-slate-800 hover:bg-slate-800/50 cursor-pointer">
                <td className="px-4 py-2 font-mono text-xs">{r.payment_id || r.id}</td>
                <td className="px-4 py-2 text-right">{inr(r.amount)}</td>
                <td className="px-4 py-2">{r.failure_reason || "—"}</td>
                <td className="px-4 py-2">{r.selected_action || "—"}</td>
                <td className="px-4 py-2">
                  <span className={`px-2 py-0.5 rounded text-xs ${STATUS_COLORS[r.status] || ""}`}>{r.status}</span>
                </td>
                <td className="px-4 py-2 text-right text-emerald-400">
                  {r.recovered_amount > 0 ? inr(r.recovered_amount) : "—"}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan="6" className="px-4 py-8 text-center text-slate-500">
                ReclaimAI hasn't detected any recoverable revenue yet.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
      {sel && <Detail id={sel} onClose={() => setSel(null)} />}
    </div>
  );
}
