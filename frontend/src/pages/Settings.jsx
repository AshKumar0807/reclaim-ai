// FILE: frontend/src/pages/Settings.jsx
// Razorpay connection status + connect/disconnect (secrets stay server-side).
import { useEffect, useState } from "react";
import { api } from "../api";

export default function Settings({ merchant, onChange }) {
  const [status, setStatus] = useState(null);
  async function refresh() { setStatus(await api.razorpayStatus()); }
  useEffect(() => { refresh().catch(console.error); }, []);

  async function connect() {
    await api.connectRazorpay();
    const m = await api.merchant();
    onChange(m); refresh();
  }

  return (
    <div className="space-y-4 max-w-lg">
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <h2 className="font-semibold mb-3">Razorpay</h2>
        {status ? (
          <div className="text-sm space-y-1">
            <div>Connection: <b className={status.connected ? "text-emerald-400" : "text-rose-400"}>
              {status.connected ? "Connected ✓" : "Disconnected"}</b></div>
            <div>Environment: {merchant?.environment}</div>
            <div>Webhook: {status.webhook_status}</div>
            <div>Account: {status.account_ref_masked || "••••"}</div>
            <div>Last webhook: {status.last_webhook_at || "—"}</div>
          </div>
        ) : <div className="text-slate-400 text-sm">Loading…</div>}
        <button onClick={connect}
          className="mt-4 px-4 py-2 rounded-lg bg-emerald-500 text-slate-900 font-semibold text-sm">
          {status?.connected ? "Reconnect" : "Connect Razorpay"}
        </button>
      </div>
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 text-sm text-slate-400">
        <h2 className="font-semibold text-slate-100 mb-2">Recovery policy (guardrails)</h2>
        Max discount, daily spend cap, customer cooldown, high-value approval threshold, and
        maximum attempts are enforced server-side and configurable per merchant.
      </div>
    </div>
  );
}
