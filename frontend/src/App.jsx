// FILE: frontend/src/App.jsx
// Top-level SPA shell: login gate + merchant-scoped dashboard with tabs.
import React, { useEffect, useState } from "react";
import { api, getToken, clearToken, openStream } from "./api";
import Login from "./pages/Login.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Recoveries from "./pages/Recoveries.jsx";
import Approvals from "./pages/Approvals.jsx";
import Audit from "./pages/Audit.jsx";
import Settings from "./pages/Settings.jsx";

const TABS = [
  { name: "Dashboard", icon: "⌂" },
  { name: "Recoveries", icon: "↗" },
  { name: "Approvals", icon: "!" },
  { name: "Audit", icon: "≡" },
  { name: "Settings", icon: "⚙" },
];
<<<<<<< HEAD

class PageErrorBoundary extends React.Component {
  state = { hasError: false };
  static getDerivedStateFromError() { return { hasError: true }; }
  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <div className="panel max-w-xl p-8">
        <div className="text-rose-300 font-bold">This view could not be displayed</div>
        <p className="text-sm text-slate-400 mt-2">The recovery data was incomplete or unavailable. Try loading the view again.</p>
        <button className="mt-5 rounded-lg bg-violet-500 px-4 py-2 text-sm font-bold" onClick={() => this.setState({ hasError: false })}>Try again</button>
      </div>
    );
  }
}
=======
>>>>>>> main

export default function App() {
  const [authed, setAuthed] = useState(!!getToken());
  const [tab, setTab] = useState("Dashboard");
  const [merchant, setMerchant] = useState(null);
  const [toast, setToast] = useState(null);
  const [tick, setTick] = useState(0); // bump to force child refresh on SSE
  const [approvals, setApprovals] = useState([]);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    if (!authed) return;
    api.merchant().then(setMerchant).catch(() => setAuthed(false));
    api.approvals().then(setApprovals).catch(() => setApprovals([]));
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
    <div className="min-h-screen bg-[#080b12]">
      <header className="topbar">
        <button className="mobile-menu" onClick={() => setSidebarOpen((open) => !open)} aria-label="Toggle navigation">☰</button>
        <div className="brand"><span className="brand-mark">R</span><span>Reclaim<span className="brand-accent">AI</span></span></div>
        <div className="topbar-right">
          <span className="mode-pill"><span className="pulse-dot" /> {merchant?.environment === "live" ? "Live Mode" : "Simulation Mode"}</span>
          <span className="merchant-name">{merchant?.name || "Merchant"} <span className="muted">⌄</span></span>
          <span className="connection"><span className="status-dot" /> Connected</span>
          <button onClick={logout} className="logout">Logout</button>
        </div>
      </header>
      <aside className={`sidebar ${sidebarOpen ? "sidebar-open" : ""}`}>
        <div className="sidebar-label">Workspace</div>
        <nav className="nav-list">
          {TABS.map((item) => (
            <button key={item.name} onClick={() => { setTab(item.name); setSidebarOpen(false); }}
              className={`nav-item ${tab === item.name ? "nav-item-active" : ""}`}>
              <span className="nav-icon">{item.icon}</span><span>{item.name}</span>
              {item.name === "Approvals" && approvals.length > 0 && <span className="nav-badge">{approvals.length}</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-label">Payment connection</div>
          <div className="connection-card">
            <div className="razorpay-logo">r</div>
            <div><div className="font-medium">Razorpay</div><div className="text-xs text-emerald-400"><span className="status-dot" /> {merchant?.razorpay_connected ? "Connected" : "Disconnected"}</div></div>
          </div>
          <div className="text-xs text-slate-500 mt-3">{merchant?.environment === "live" ? "Live Mode" : "Test Mode"}</div>
        </div>
      </aside>

      {toast && (
        <div className="fixed top-4 right-4 z-50 bg-emerald-600 text-white text-sm px-4 py-2 rounded-lg shadow-lg">
          🔔 {toast}
        </div>
      )}

      <main className="main-content">
<<<<<<< HEAD
        <PageErrorBoundary key={tab}>
          {tab === "Dashboard" && <Dashboard tick={tick} onNavigate={setTab} />}
          {tab === "Recoveries" && <Recoveries tick={tick} />}
          {tab === "Approvals" && <Approvals tick={tick} />}
          {tab === "Audit" && <Audit tick={tick} />}
          {tab === "Settings" && <Settings merchant={merchant} onChange={setMerchant} />}
        </PageErrorBoundary>
=======
        {tab === "Dashboard" && <Dashboard tick={tick} onNavigate={setTab} />}
        {tab === "Recoveries" && <Recoveries tick={tick} />}
        {tab === "Approvals" && <Approvals tick={tick} />}
        {tab === "Audit" && <Audit tick={tick} />}
        {tab === "Settings" && <Settings merchant={merchant} onChange={setMerchant} />}
>>>>>>> main
      </main>
    </div>
  );
}
