// FILE: frontend/src/pages/Approvals.jsx
// Human approval queue (spec 9). Approve/Reject are idempotent server-side; a
// double-click yields HTTP 409 and executes no second action.
import { useEffect, useState } from "react";
import { api, inr } from "../api";

export default function Approvals({ tick }) {
  const [rows, setRows] = useState([]);
  const [msg, setMsg] = useState(null);

  async function refresh() { setRows(await api.approvals()); }
  useEffect(() => { refresh().catch(console.error); }, [tick]);

  async function decide(id, kind) {
    try {
      await (kind === "approve" ? api.approve(id) : api.reject(id));
      setMsg(`${kind}d ${id}`);
    } catch (e) {
      setMsg(String(e).includes("409") ? "Already processed (idempotent)" : "Error");
    } finally {
      setTimeout(() => setMsg(null), 3000);
      refresh();
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex justify-between items-center">
        <h2 className="text-lg font-semibold">Approval queue</h2>
        {msg && <span className="text-xs text-amber-300">{msg}</span>}
      </div>
      <div className="text-sm text-slate-400">These interventions were paused by deterministic guardrails. Review the reason before approving.</div>
      {rows.length === 0 && <div className="text-slate-500 text-sm">Nothing pending. 🎉</div>}
      <div className="grid gap-3">
        {rows.map((a) => (
          <div key={a.id} className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <div className="text-xs uppercase text-slate-500">High value recovery</div>
            <div className="mt-1 grid grid-cols-2 gap-2 text-sm">
              <div>Customer <div className="font-medium">{a.customer_ref || "—"}</div></div>
              <div>Amount <div className="font-medium">{inr(a.amount)}</div></div>
              <div>Action <div className="font-medium">{a.action_type}</div></div>
              <div>Risk <div className="font-medium">{a.risk}</div></div>
            </div>
            <div className="text-xs text-slate-400 mt-2">Guardrail: {a.reason}</div>
            <div className="flex gap-2 mt-3">
              <button onClick={() => decide(a.id, "approve")}
                className="px-3 py-1 rounded bg-emerald-500 text-slate-900 text-xs font-semibold">Approve</button>
              <button onClick={() => decide(a.id, "reject")}
                className="px-3 py-1 rounded bg-rose-500/80 text-white text-xs font-semibold">Reject</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
