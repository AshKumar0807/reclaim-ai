// FILE: frontend/src/api.js
// API client. All calls go through FastAPI (spec 14: React never talks to
// Razorpay/DB/agent directly). JWT is stored in localStorage and attached as a
// Bearer header; SSE receives the token via query string.
const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export function getToken() { return localStorage.getItem("reclaim_token"); }
export function setToken(t) { localStorage.setItem("reclaim_token", t); }
export function clearToken() { localStorage.removeItem("reclaim_token"); }

async function req(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  const tok = getToken();
  if (tok) headers["Authorization"] = `Bearer ${tok}`;
  const res = await fetch(`${BASE}${path}`, { ...options, headers });
  if (res.status === 401) { clearToken(); throw new Error("unauthorized"); }
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.status === 204 ? null : res.json();
}

export const api = {
  base: BASE,
  login: (email, password) =>
    req("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  merchant: () => req("/api/merchant"),
  connectRazorpay: () => req("/api/merchant/razorpay/connect", { method: "POST" }),
  razorpayStatus: () => req("/api/merchant/razorpay/status"),
  metrics: () => req("/api/dashboard/metrics"),
  pipeline: () => req("/api/dashboard/pipeline"),
  recoveries: (qs = "") => req(`/api/recoveries${qs}`),
  recovery: (id) => req(`/api/recoveries/${id}`),
  approvals: () => req("/api/approvals"),
  approve: (id) => req(`/api/approvals/${id}/approve`, { method: "POST" }),
  reject: (id) => req(`/api/approvals/${id}/reject`, { method: "POST" }),
  audit: (qs = "") => req(`/api/audit${qs}`),
  simulate: (body) => req("/webhooks/simulate", { method: "POST", body: JSON.stringify(body) }),
};

// Subscribe to server-sent recovery.* events for live dashboard updates.
export function openStream(onEvent) {
  const tok = getToken();
  if (!tok) return () => {};
  const es = new EventSource(`${BASE}/api/stream?token=${encodeURIComponent(tok)}`);
  const names = ["recovery.detected", "recovery.diagnosed", "recovery.action_selected",
    "recovery.approval_required", "recovery.executed", "recovery.recovered",
    "recovery.failed", "recovery.escalated"];
  names.forEach((n) => es.addEventListener(n, (e) => onEvent(n, JSON.parse(e.data || "{}"))));
  return () => es.close();
}

export const inr = (paise) => "₹" + (Number(paise || 0) / 100).toLocaleString("en-IN", { maximumFractionDigits: 0 });
