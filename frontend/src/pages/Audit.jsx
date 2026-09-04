// FILE: frontend/src/pages/Audit.jsx
import { useEffect, useState } from "react";
import { api } from "../api";

export default function Audit({ tick }) {
  const [rows, setRows] = useState([]);
  useEffect(() => { api.audit("?limit=200").then(setRows).catch(console.error); }, [tick]);
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800 font-semibold">Audit log (append-only)</div>
      <div className="max-h-[70vh] overflow-auto">
        <table className="w-full text-sm">
          <thead className="text-slate-400 text-xs sticky top-0 bg-slate-900">
            <tr><th className="text-left px-4 py-2">Time</th><th className="text-left px-4 py-2">Actor</th>
            <th className="text-left px-4 py-2">Action</th><th className="text-left px-4 py-2">Event</th>
            <th className="text-left px-4 py-2">Recovery</th><th className="text-left px-4 py-2">Rationale</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t border-slate-800">
                <td className="px-4 py-2 text-xs text-slate-500">{r.created_at}</td>
                <td className="px-4 py-2">{r.actor}</td>
                <td className="px-4 py-2">{r.action}</td>
                <td className="px-4 py-2 text-xs">{r.event_type || "—"}</td>
                <td className="px-4 py-2 font-mono text-xs">{r.recovery_event_id || "—"}</td>
                <td className="px-4 py-2 text-slate-400">{r.rationale}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
