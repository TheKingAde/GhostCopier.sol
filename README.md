# 👻 GhostCopier

Paper copy-trading simulator for Solana wallets. Point it at one or more
wallet addresses, give it a starting USD balance, and it watches those
wallets live on-chain and mirrors their buys/sells into a fake portfolio
so you can see how "copying the whale" would have actually gone — with
zero real money or private keys involved.

## Stack

- **Backend:** Python, Quart (async Flask), aiosqlite (SQLite), httpx
- **Frontend:** vanilla JS/HTML/CSS (no build step), gmgn-inspired dark
  trading-terminal theme with a "ghost" signature accent

## How it works

1. **Session** = a starting USD balance (converted to SOL at the current
   price) + one or more wallet addresses to copy.
2. A background task polls each wallet's recent transactions via Solana
   RPC (`getSignaturesForAddress` / `getTransaction`).
3. Each new transaction is run through a heuristic swap detector
   (`app/trade_parser.py`): it diffs the wallet's pre/post SOL balance
   and pre/post SPL token balances. If SOL went down and a token went up
   → BUY; the reverse → SELL. This works across DEXes (Jupiter, Raydium,
   Orca, Pump.fun, ...) without needing per-program instruction parsing.
4. The paper trading engine (`app/paper_trader.py`) sizes and applies the
   equivalent trade against the session's virtual SOL balance / token
   position, applying simulated slippage + fees, and writes a full trade
   record (see **Position sizing** below).
5. Everything is persisted to SQLite so sessions survive a restart, and
   any session that was `running` is automatically resumed on boot.

## Running it

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then edit SOLANA_RPC_URL, see note below
python3 run.py
```

Open `http://localhost:5000`.

### ⚠️ About the RPC endpoint

The public `api.mainnet-beta.solana.com` endpoint is rate limited and
will cause missed or delayed trades under any real use — it's only fine
for quick local testing with a low poll frequency. For anything real,
get a free API key from **Helius**, **QuickNode**, or **Triton** and set
`SOLANA_RPC_URL` in `.env` to your dedicated endpoint.

## Position sizing strategies

Set per-session when you create it:

- **Mirror wallet % (`proportional`, default):** if the copied wallet
  spent 8% of its own SOL balance on a buy, the session spends 8% of its
  balance too. Sells mirror the % of their token position they sold.
  This is the more realistic "copy trade" behavior.
- **Fixed % per trade (`fixed_pct`):** always risks a fixed slice (e.g.
  10%) of the *current* session balance on every buy, and sells that
  same fixed % of any held position. More predictable, less realistic.

Every session also has independently configurable **simulated slippage**
and **fee** percentages, applied against the trade price in the
direction that hurts you (buys pay slightly more, sells receive slightly
less) — so results aren't unrealistically clean.

## Things worth knowing (and a few I added beyond the brief)

- **Idempotent by transaction signature** — each `(session, tx, token,
  side)` triple is unique in the DB, so re-polling the same signature
  (or restarting the app) never double-counts a trade.
- **Skipped trades are recorded, not silently dropped.** If a wallet
  sells a token the session never bought, or a buy can't be sized
  because the session is out of balance, a `SKIPPED` row is still
  written with a `note` explaining why — so the trade history is a
  complete, honest log of everything the copied wallet did.
- **Realized vs. unrealized PnL.** Realized PnL accrues on sells (actual
  SOL back vs. cost basis). Open positions are currently valued at cost
  basis (no live per-token price feed is wired in), so unrealized PnL on
  *still-open* positions reads as flat until you plug in a token price
  API (Birdeye/Jupiter Price API are natural choices) — this is called
  out directly in the UI rather than faking a number.
- **Address validation** happens both client- and server-side (base58 +
  32-byte decode check) before a wallet can be added.
- **Start/Pause/Stop** are distinct: Stop fully halts polling and resets
  wallet "last seen" tracking is preserved; Pause just idles the loop.
  Sessions can be resumed later without losing history or positions.
- **Multiple wallets per session** are fully supported, addable and
  removable at any time from the session page, and every trade row
  records exactly which wallet it was copied from ("Copied from"
  column).
- **No private keys, ever.** This tool only ever reads public on-chain
  data — there is nothing here that could sign or broadcast a real
  transaction.

### Natural next steps (not built, to keep scope sane)

- A live token price feed for accurate unrealized PnL on open positions.
- WebSocket/SSE push instead of polling the API every few seconds.
- CSV export of trade history.
- Multi-wallet trade collision handling (two copied wallets buying the
  same token within a poll window currently just applies both trades in
  order — fine for most cases, but worth a dedicated queue if you're
  copying many high-frequency wallets at once).

## Project layout

```
ghostcopier/
├── run.py                  entrypoint
├── app/
│   ├── __init__.py         Quart app factory + lifecycle hooks
│   ├── config.py           env-driven settings
│   ├── db.py                async SQLite data layer
│   ├── solana_client.py    RPC + SOL price + token symbol lookups
│   ├── trade_parser.py     on-chain swap detection heuristic
│   ├── sizing.py           position sizing strategies
│   ├── paper_trader.py     the simulation engine
│   ├── monitor.py          background per-session polling tasks
│   ├── routes.py           pages + REST API
│   └── utils.py            address validation helpers
├── templates/               Jinja pages (dashboard, session detail)
└── static/
    ├── css/style.css
    └── js/ (api.js, dashboard.js, session.js)
```
