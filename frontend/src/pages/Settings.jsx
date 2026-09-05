import { useEffect, useState } from "react";
import { api } from "../api";

function SettingRow({ label, value, tone = "text-slate-200" }) { return <div className="flex justify-between gap-4 py-3 border-b border-slate-800/70 last:border-0"><span className="text-sm text-slate-500">{label}</span><span className={`text-sm text-right ${tone}`}>{value}</span></div>; }

export default function Settings({ merchant, onChange }) {
  const [status, setStatus] = useState(null); const [busy, setBusy] = useState(false); const [error, setError] = useState(null);
  async function refresh() { setStatus(await api.razorpayStatus()); }
  useEffect(() => { refresh().catch(() => setError("Unable to load connection status.")); }, []);
  async function connect() { setBusy(true); setError(null); try { await api.connectRazorpay(); onChange(await api.merchant()); await refresh(); } catch { setError("Unable to update the Razorpay connection."); } finally { setBusy(false); } }
  return <div className="space-y-6 max-w-3xl"><div><div className="page-eyebrow">Configuration</div><h1 className="page-title mt-2">Settings</h1><p className="text-sm text-slate-400 mt-2">Manage your merchant connection and recovery policies.</p></div>
    {error && <div className="panel p-4 text-sm text-rose-300">{error}</div>}
    <section className="panel p-5"><div className="panel-title mb-3">Merchant</div><SettingRow label="Merchant name" value={merchant?.name || "—"} /><SettingRow label="Merchant ID" value={merchant?.merchant_id || "—"} /><SettingRow label="Account status" value="Active" tone="text-emerald-300" /></section>
    <section className="panel p-5"><div className="flex justify-between items-center mb-3"><div className="panel-title">Razorpay connection</div><span className={`status-pill ${status?.connected ? "status-success" : "status-danger"}`}>{status?.connected ? "Connected" : "Disconnected"}</span></div><SettingRow label="Environment" value={merchant?.environment === "live" ? "Live mode" : "Test mode"} /><SettingRow label="Webhook status" value={status?.webhook_status || merchant?.webhook_status || "—"} /><SettingRow label="Account reference" value={status?.account_ref_masked || "••••"} /><SettingRow label="Last webhook" value={status?.last_webhook_at || "—"} /><button disabled={busy} onClick={connect} className="mt-5 rounded-lg bg-violet-500 px-4 py-2 text-sm font-bold text-white disabled:opacity-50">{busy ? "Updating…" : status?.connected ? "Reconnect Razorpay" : "Connect Razorpay"}</button></section>
    <section className="panel p-5"><div className="panel-title mb-3">Recovery policies</div><SettingRow label="Autonomous recovery limit" value="Configured server-side" /><SettingRow label="Maximum discount" value="Configured server-side" /><SettingRow label="Contact cooldown" value="Configured server-side" /><SettingRow label="Approval threshold" value="Configured server-side" /><p className="text-xs text-slate-600 mt-4">Guardrails are enforced by the backend. Secret credentials are never exposed in the browser.</p></section>
  </div>;
}
