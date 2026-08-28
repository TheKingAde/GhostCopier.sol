// Dashboard: sessions table, stats, new-session modal.

const els = {
  tbody: document.getElementById("sessions-tbody"),
  empty: document.getElementById("sessions-empty"),
  table: document.getElementById("sessions-table"),
  statTotal: document.getElementById("stat-total-sessions"),
  statLive: document.getElementById("stat-live-sessions"),
  statEquity: document.getElementById("stat-total-equity"),
  statPnl: document.getElementById("stat-total-pnl"),

  modalBackdrop: document.getElementById("modal-backdrop"),
  form: document.getElementById("form-new-session"),
  walletInputs: document.getElementById("wallet-inputs"),
  formError: document.getElementById("form-error"),
  solPreview: document.getElementById("sol-preview"),
  sizingMode: document.getElementById("sizing-mode"),
  sizingPctLabel: document.getElementById("sizing-pct-label"),
};

let currentSolPrice = 150;

function openModal() {
  els.formError.classList.add("hidden");
  els.form.reset();
  els.walletInputs.innerHTML = "";
  addWalletRow();
  updateSizingLabel();
  els.modalBackdrop.classList.remove("hidden");
}
function closeModal() { els.modalBackdrop.classList.add("hidden"); }

document.getElementById("btn-new-session").addEventListener("click", openModal);
document.getElementById("btn-new-session-empty")?.addEventListener("click", openModal);
document.getElementById("modal-close").addEventListener("click", closeModal);
document.getElementById("btn-cancel").addEventListener("click", closeModal);
els.modalBackdrop.addEventListener("click", (e) => { if (e.target === els.modalBackdrop) closeModal(); });

function addWalletRow(value = "") {
  const row = document.createElement("div");
  row.className = "wallet-input-row";
  row.innerHTML = `
    <input type="text" class="wallet-address-input" placeholder="Solana wallet address" value="${value}" required>
    <button type="button" class="icon-btn remove-wallet-row" title="Remove">×</button>
  `;
  row.querySelector(".remove-wallet-row").addEventListener("click", () => {
    if (els.walletInputs.children.length > 1) row.remove();
  });
  els.walletInputs.appendChild(row);
}
document.getElementById("btn-add-wallet-row").addEventListener("click", () => addWalletRow());

document.querySelector('input[name="start_amount_usd"]').addEventListener("input", (e) => {
  const usd = parseFloat(e.target.value) || 0;
  const sol = currentSolPrice ? usd / currentSolPrice : 0;
  els.solPreview.textContent = `≈ ${sol.toLocaleString(undefined, { maximumFractionDigits: 4 })} SOL at current price ($${currentSolPrice.toFixed(2)})`;
});

function updateSizingLabel() {
  els.sizingPctLabel.textContent = els.sizingMode.value === "fixed_pct"
    ? "Size per trade (%)"
    : "Cap on mirrored % (safety ceiling)";
}
els.sizingMode.addEventListener("change", updateSizingLabel);

els.form.addEventListener("submit", async (e) => {
  e.preventDefault();
  els.formError.classList.add("hidden");

  const fd = new FormData(els.form);
  const wallets = Array.from(document.querySelectorAll(".wallet-address-input"))
    .map(i => i.value.trim())
    .filter(Boolean);

  const payload = {
    name: fd.get("name"),
    start_amount_usd: parseFloat(fd.get("start_amount_usd")),
    wallets,
    sizing_mode: fd.get("sizing_mode"),
    sizing_pct: parseFloat(fd.get("sizing_pct")),
    slippage_pct: parseFloat(fd.get("slippage_pct")),
    fee_pct: parseFloat(fd.get("fee_pct")),
    autostart: true,
  };

  const submitBtn = els.form.querySelector('button[type="submit"]');
  submitBtn.disabled = true;
  submitBtn.textContent = "Creating…";

  try {
    const session = await Api.createSession(payload);
    closeModal();
    toast("Session created and live 👻", "success");
    window.location.href = `/session/${session.id}`;
  } catch (err) {
    els.formError.textContent = err.message;
    els.formError.classList.remove("hidden");
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Create & start session";
  }
});

// ---------------------------------------------------------------- render

function statusBadge(session) {
  const status = session.status;
  const label = status.charAt(0).toUpperCase() + status.slice(1);
  return `<span class="status-badge ${status}"><span class="dot"></span>${label}</span>`;
}

function renderSessions(sessions) {
  els.table.classList.toggle("hidden", sessions.length === 0);
  els.empty.classList.toggle("hidden", sessions.length !== 0);

  els.tbody.innerHTML = sessions.map(s => `
    <tr class="clickable" data-id="${s.id}">
      <td>${statusBadge(s)}</td>
      <td>
        <div style="font-weight:600">${escapeHtml(s.name)}</div>
        <div class="mono" style="font-size:11px;color:var(--text-faint)">${s.id.slice(0,8)}</div>
      </td>
      <td>${s.wallet_count} wallet${s.wallet_count === 1 ? "" : "s"}</td>
      <td>
        <div class="mono">${Fmt.usd(s.balance_usd)}</div>
        <div class="mono" style="font-size:11px;color:var(--text-faint)">${Fmt.sol(s.sol_balance, 3)}</div>
      </td>
      <td class="mono ${Fmt.pnlClass(s.pnl_usd)}">${Fmt.usd(s.pnl_usd)} <span style="font-size:11px">(${Fmt.pct(s.pnl_pct)})</span></td>
      <td class="mono" style="color:var(--text-dim)">${Fmt.timeAgo(s.created_at)}</td>
      <td>
        <button class="btn btn-ghost btn-sm open-btn" data-id="${s.id}">Open →</button>
      </td>
    </tr>
  `).join("");

  els.tbody.querySelectorAll("tr").forEach(row => {
    row.addEventListener("click", (e) => {
      if (e.target.closest(".open-btn")) return;
      window.location.href = `/session/${row.dataset.id}`;
    });
  });
  els.tbody.querySelectorAll(".open-btn").forEach(btn => {
    btn.addEventListener("click", () => { window.location.href = `/session/${btn.dataset.id}`; });
  });

  const totalEquity = sessions.reduce((a, s) => a + (s.total_value_usd || 0), 0);
  const totalPnl = sessions.reduce((a, s) => a + (s.pnl_usd || 0), 0);
  const liveCount = sessions.filter(s => s.status === "running").length;

  els.statTotal.textContent = sessions.length;
  els.statLive.textContent = liveCount;
  els.statEquity.textContent = Fmt.usd(totalEquity);
  els.statPnl.textContent = Fmt.usd(totalPnl);
  els.statPnl.className = `stat-value ${Fmt.pnlClass(totalPnl)}`;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

async function loadSessions() {
  try {
    const sessions = await Api.listSessions();
    if (sessions[0]) currentSolPrice = sessions[0].sol_price_usd || currentSolPrice;
    renderSessions(sessions);
  } catch (err) {
    toast("Failed to load sessions: " + err.message, "error");
  }
}

loadSessions();
setInterval(loadSessions, 6000);

Api.solPrice().then(r => { currentSolPrice = r.sol_usd; }).catch(() => {});
