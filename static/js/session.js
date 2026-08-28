// Session detail page: balance, wallets, positions, trade history, controls.

const root = document.getElementById("session-app");
const sessionId = root.dataset.sessionId;

const els = {
  name: document.getElementById("session-name"),
  statusBadge: document.getElementById("session-status-badge"),
  errorBanner: document.getElementById("session-error-banner"),

  btnStart: document.getElementById("btn-start"),
  btnPause: document.getElementById("btn-pause"),
  btnStop: document.getElementById("btn-stop"),
  btnDelete: document.getElementById("btn-delete"),

  balSol: document.getElementById("bal-sol"),
  balUsd: document.getElementById("bal-usd"),
  balTotalUsd: document.getElementById("bal-total-usd"),
  balPnl: document.getElementById("bal-pnl"),
  balPnlPct: document.getElementById("bal-pnl-pct"),
  balRealized: document.getElementById("bal-realized"),
  balStart: document.getElementById("bal-start"),
  balStartSol: document.getElementById("bal-start-sol"),

  walletsList: document.getElementById("wallets-list"),
  addWalletForm: document.getElementById("form-add-wallet"),
  addWalletInput: document.getElementById("add-wallet-input"),
  walletFormError: document.getElementById("wallet-form-error"),

  positionsTbody: document.getElementById("positions-tbody"),
  positionsEmpty: document.getElementById("positions-empty"),
  positionsTable: document.getElementById("positions-table"),

  tradesTbody: document.getElementById("trades-tbody"),
  tradesEmpty: document.getElementById("trades-empty"),
  tradesTable: document.getElementById("trades-table"),
};

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function setControlsForStatus(status) {
  els.btnStart.disabled = status === "running";
  els.btnPause.disabled = status !== "running";
  els.btnStop.disabled = status === "stopped";
}

function renderSession(s) {
  els.name.textContent = s.name;
  document.title = `${s.name} · GhostCopier`;

  const label = s.status.charAt(0).toUpperCase() + s.status.slice(1);
  els.statusBadge.className = `status-badge ${s.status}`;
  els.statusBadge.innerHTML = `<span class="dot"></span>${label}`;
  setControlsForStatus(s.status);

  els.errorBanner.textContent = s.last_error ? `⚠ ${s.last_error}` : "";

  els.balSol.textContent = Fmt.sol(s.sol_balance);
  els.balUsd.textContent = Fmt.usd(s.balance_usd);
  els.balTotalUsd.textContent = Fmt.usd(s.total_value_usd);

  els.balPnl.textContent = Fmt.usd(s.pnl_usd);
  els.balPnl.className = `stat-value ${Fmt.pnlClass(s.pnl_usd)}`;
  els.balPnlPct.textContent = Fmt.pct(s.pnl_pct);

  els.balRealized.textContent = Fmt.usd(s.realized_pnl_usd);
  els.balRealized.className = `stat-value ${Fmt.pnlClass(s.realized_pnl_usd)}`;

  els.balStart.textContent = Fmt.usd(s.start_amount_usd);
  els.balStartSol.textContent = `${Fmt.sol(s.start_sol_balance, 3)} @ $${s.sol_price_at_start.toFixed(2)}`;

  renderWallets(s.wallets || []);
  renderPositions(s.positions || []);
}

function renderWallets(wallets) {
  if (!wallets.length) {
    els.walletsList.innerHTML = `<p style="color:var(--text-dim);font-size:13px">No wallets added.</p>`;
    return;
  }
  els.walletsList.innerHTML = wallets.map(w => `
    <div class="wallet-row" data-address="${w.address}">
      <div>
        <a class="addr" href="${Fmt.solscanAddr(w.address)}" target="_blank" rel="noopener">${Fmt.shortAddr(w.address)}</a>
        ${w.label ? `<span style="color:var(--text-dim);font-size:12px;margin-left:6px">${escapeHtml(w.label)}</span>` : ""}
      </div>
      <button class="icon-btn remove-wallet-btn" title="Stop copying this wallet">×</button>
    </div>
  `).join("");

  els.walletsList.querySelectorAll(".remove-wallet-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      const row = btn.closest(".wallet-row");
      const address = row.dataset.address;
      if (!confirm(`Stop copying ${Fmt.shortAddr(address)}?`)) return;
      try {
        await Api.removeWallet(sessionId, address);
        toast("Wallet removed", "success");
        refresh();
      } catch (err) {
        toast(err.message, "error");
      }
    });
  });
}

function renderPositions(positions) {
  const open = positions.filter(p => p.amount > 0.00000001);
  els.positionsTable.classList.toggle("hidden", open.length === 0);
  els.positionsEmpty.classList.toggle("hidden", open.length !== 0);
  els.positionsTbody.innerHTML = open.map(p => `
    <tr>
      <td>${escapeHtml(p.token_symbol || Fmt.shortAddr(p.token_mint))}</td>
      <td class="mono">${Fmt.num(p.amount)}</td>
      <td class="mono">$${Fmt.num(p.avg_cost_usd, 6)}</td>
      <td class="mono">${Fmt.usd(p.cost_value_usd)}</td>
    </tr>
  `).join("");
}

function renderTrades(trades) {
  els.tradesTable.classList.toggle("hidden", trades.length === 0);
  els.tradesEmpty.classList.toggle("hidden", trades.length !== 0);

  els.tradesTbody.innerHTML = trades.map(t => `
    <tr>
      <td class="mono" style="color:var(--text-dim)">${Fmt.dateTime(t.executed_at)}</td>
      <td><span class="side-badge ${t.side}">${t.side}</span></td>
      <td>${escapeHtml(t.token_symbol || Fmt.shortAddr(t.token_mint))}</td>
      <td class="mono">${t.token_amount ? Fmt.num(t.token_amount) : "—"}</td>
      <td class="mono">${t.price_usd_per_token ? "$" + Fmt.num(t.price_usd_per_token, 6) : "—"}</td>
      <td class="mono">${t.sol_amount ? Fmt.sol(t.sol_amount, 4) : "—"}</td>
      <td class="mono">${t.sol_amount ? Fmt.usd(t.sol_amount * (t.sol_price_usd || 0)) : "—"}</td>
      <td><a class="copied-from" href="${Fmt.solscanAddr(t.source_wallet)}" target="_blank" rel="noopener">${Fmt.shortAddr(t.source_wallet)}</a></td>
      <td class="mono">${t.session_sol_balance_after !== null ? Fmt.sol(t.session_sol_balance_after, 3) : "—"}</td>
      <td><a class="solscan-link" href="${Fmt.solscanTx(t.tx_signature)}" target="_blank" rel="noopener">view ↗</a></td>
    </tr>
  `).join("");
}

// ------------------------------------------------------------- controls

els.btnStart.addEventListener("click", async () => {
  try { await Api.startSession(sessionId); toast("Session started 👻", "success"); refresh(); }
  catch (err) { toast(err.message, "error"); }
});
els.btnPause.addEventListener("click", async () => {
  try { await Api.pauseSession(sessionId); toast("Session paused", "success"); refresh(); }
  catch (err) { toast(err.message, "error"); }
});
els.btnStop.addEventListener("click", async () => {
  try { await Api.stopSession(sessionId); toast("Session stopped", "success"); refresh(); }
  catch (err) { toast(err.message, "error"); }
});
els.btnDelete.addEventListener("click", async () => {
  if (!confirm("Delete this session permanently? This cannot be undone.")) return;
  try {
    await Api.deleteSession(sessionId);
    toast("Session deleted", "success");
    window.location.href = "/";
  } catch (err) { toast(err.message, "error"); }
});

els.addWalletForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  els.walletFormError.classList.add("hidden");
  const address = els.addWalletInput.value.trim();
  try {
    await Api.addWallet(sessionId, address);
    els.addWalletInput.value = "";
    toast("Wallet added to session", "success");
    refresh();
  } catch (err) {
    els.walletFormError.textContent = err.message;
    els.walletFormError.classList.remove("hidden");
  }
});

// --------------------------------------------------------------- refresh

async function refresh() {
  try {
    const [session, trades] = await Promise.all([
      Api.getSession(sessionId),
      Api.listTrades(sessionId),
    ]);
    renderSession(session);
    renderTrades(trades);
  } catch (err) {
    toast("Failed to refresh session: " + err.message, "error");
  }
}

refresh();
setInterval(refresh, 5000);
