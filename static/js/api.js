// Shared fetch wrapper, formatters, and small UI helpers used by both pages.

const Api = {
  async _req(method, url, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(url, opts);
    let data = null;
    try { data = await res.json(); } catch (_) { /* no body */ }
    if (!res.ok) {
      const message = (data && data.error) || `Request failed (${res.status})`;
      throw new Error(message);
    }
    return data;
  },
  get(url) { return this._req("GET", url); },
  post(url, body) { return this._req("POST", url, body ?? {}); },
  del(url) { return this._req("DELETE", url); },

  listSessions() { return this.get("/api/sessions"); },
  createSession(payload) { return this.post("/api/sessions", payload); },
  getSession(id) { return this.get(`/api/sessions/${id}`); },
  deleteSession(id) { return this.del(`/api/sessions/${id}`); },
  startSession(id) { return this.post(`/api/sessions/${id}/start`); },
  pauseSession(id) { return this.post(`/api/sessions/${id}/pause`); },
  stopSession(id) { return this.post(`/api/sessions/${id}/stop`); },
  topUpSession(id, amountUsd) { return this.post(`/api/sessions/${id}/top-up`, { amount_usd: amountUsd }); },

  listWallets(id) { return this.get(`/api/sessions/${id}/wallets`); },
  addWallet(id, address, label) { return this.post(`/api/sessions/${id}/wallets`, { address, label }); },
  removeWallet(id, address) { return this.del(`/api/sessions/${id}/wallets/${address}`); },

  listTrades(id, limit = 500) { return this.get(`/api/sessions/${id}/trades?limit=${limit}`); },
  listPositions(id) { return this.get(`/api/sessions/${id}/positions`); },

  solPrice() { return this.get("/api/sol-price"); },
};

const Fmt = {
  usd(n) {
    if (n === null || n === undefined || isNaN(n)) return "—";
    const sign = n < 0 ? "-" : "";
    const abs = Math.abs(n);
    return sign + "$" + abs.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  },
  sol(n, dp = 4) {
    if (n === null || n === undefined || isNaN(n)) return "—";
    return Number(n).toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp }) + " SOL";
  },
  num(n, dp = 4) {
    if (n === null || n === undefined || isNaN(n)) return "—";
    const abs = Math.abs(n);
    const digits = abs >= 1000 ? 2 : abs >= 1 ? 4 : 6;
    return Number(n).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: digits });
  },
  pct(n) {
    if (n === null || n === undefined || isNaN(n)) return "—";
    const sign = n > 0 ? "+" : "";
    return sign + n.toFixed(2) + "%";
  },
  pnlClass(n) {
    if (n === null || n === undefined || isNaN(n) || n === 0) return "pnl-flat";
    return n > 0 ? "pnl-pos" : "pnl-neg";
  },
  shortAddr(addr) {
    if (!addr) return "";
    return addr.slice(0, 4) + "…" + addr.slice(-4);
  },
  timeAgo(ts) {
    if (!ts) return "—";
    const diff = Date.now() / 1000 - ts;
    if (diff < 60) return Math.floor(diff) + "s ago";
    if (diff < 3600) return Math.floor(diff / 60) + "m ago";
    if (diff < 86400) return Math.floor(diff / 3600) + "h ago";
    return Math.floor(diff / 86400) + "d ago";
  },
  dateTime(ts) {
    if (!ts) return "—";
    const d = new Date(ts * 1000);
    return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
  },
  solscanTx(sig) { return `https://solscan.io/tx/${sig}`; },
  solscanAddr(addr) { return `https://solscan.io/account/${addr}`; },
};

function toast(message, type = "success") {
  const root = document.getElementById("toast-root");
  if (!root) return;
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  root.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

async function refreshSolPricePill() {
  try {
    const { sol_usd } = await Api.solPrice();
    const el = document.getElementById("sol-price-value");
    if (el) el.textContent = "$" + sol_usd.toFixed(2);
  } catch (_) { /* silent - non critical */ }
}
refreshSolPricePill();
setInterval(refreshSolPricePill, 30000);
