// FILE: frontend/src/App.jsx
// Top-level SPA shell: login gate + merchant-scoped dashboard with tabs.
import { useEffect, useState } from "react";
import { api, getToken, clearToken, openStream } from "./api";
import Login from "./pages/Login.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Recoveries from "./pages/Recoveries.jsx";
import Approvals from "./pages/Approvals.jsx";
import Audit from "./pages/Audit.jsx";
import Settings from "./pages/Settings.jsx";

const TABS = ["Dashboard", "Recoveries", "Approvals", "Audit", "Settings"];

export default function App() {
  const [authed, setAuthed] = useState(!!getToken());
  const [tab, setTab] = useState("Dashboard");
  const [merchant, setMerchant] = useState(null);
  const [toast, setToast] = useState(null);
  const [tick, setTick] = useState(0); // bump to force child refresh on SSE

  useEffect(() => {
    if (!authed) return;
    api.merchant().then(setMerchant).catch(() => setAuthed(false));
    const close = openStream((name, data) => {
      setToast(`${name}${data.recovery_event_id ? " · " + data.recovery_event_id : ""}`);
      setTick((t) => t + 1);
      setTimeout(() => setToast(null), 3500);
    });
    return close;
  }, [authed]);

  if (!authed) return <Login onSuccess={() => setAuthed(true)} />;

  const logout = () => { clearToken(); setAuthed(false); };

  return (
    <div className="min-h-screen">
      <header className="flex items-center justify-between px-6 py-4 border-b border-slate-800">
        <div>
          <h1 className="text-xl font-bold">ReclaimAI</h1>
          <p className="text-xs text-slate-400">
            {merchant ? `${merchant.name} · ${merchant.environment} · webhook ${merchant.webhook_status}` : "…"}
          </p>
        </div>
        <nav className="flex gap-1">
          {TABS.map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-3 py-1.5 rounded-lg text-sm ${tab === t ? "bg-emerald-500 text-slate-900 font-semibold" : "text-slate-300 hover:bg-slate-800"}`}>
              {t}
            </button>
          ))}
          <button onClick={logout} className="ml-2 px-3 py-1.5 rounded-lg text-sm text-slate-400 hover:bg-slate-800">Logout</button>
        </nav>
      </header>

      {toast && (
        <div className="fixed top-4 right-4 z-50 bg-emerald-600 text-white text-sm px-4 py-2 rounded-lg shadow-lg">
          🔔 {toast}
        </div>
      )}

      <main className="p-6 max-w-7xl mx-auto">
        {tab === "Dashboard" && <Dashboard tick={tick} />}
        {tab === "Recoveries" && <Recoveries tick={tick} />}
        {tab === "Approvals" && <Approvals tick={tick} />}
        {tab === "Audit" && <Audit tick={tick} />}
        {tab === "Settings" && <Settings merchant={merchant} onChange={setMerchant} />}
      </main>
    </div>
  );
}
