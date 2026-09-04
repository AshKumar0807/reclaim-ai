// FILE: frontend/src/pages/Login.jsx
import { useState } from "react";
import { api, setToken } from "../api";

export default function Login({ onSuccess }) {
  const [email, setEmail] = useState("owner@example.com");
  const [password, setPassword] = useState("reclaim123");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      const r = await api.login(email, password);
      setToken(r.access_token);
      onSuccess();
    } catch {
      setErr("Invalid credentials");
    } finally { setBusy(false); }
  }

  return (
    <div className="min-h-screen flex items-center justify-center">
      <form onSubmit={submit} className="bg-slate-900 border border-slate-800 rounded-2xl p-8 w-96 space-y-4">
        <div>
          <h1 className="text-2xl font-bold">ReclaimAI</h1>
          <p className="text-sm text-slate-400">Automated revenue recovery · human approval · full auditability</p>
        </div>
        <input className="w-full bg-slate-800 rounded-lg px-3 py-2" value={email}
          onChange={(e) => setEmail(e.target.value)} placeholder="Email" />
        <input type="password" className="w-full bg-slate-800 rounded-lg px-3 py-2" value={password}
          onChange={(e) => setPassword(e.target.value)} placeholder="Password" />
        {err && <div className="text-rose-400 text-sm">{err}</div>}
        <button disabled={busy}
          className="w-full bg-emerald-500 text-slate-900 font-semibold py-2 rounded-lg disabled:opacity-50">
          {busy ? "Signing in…" : "Connect Razorpay & Sign in"}
        </button>
        <p className="text-xs text-slate-500">Demo: owner@example.com / reclaim123</p>
      </form>
    </div>
  );
}
