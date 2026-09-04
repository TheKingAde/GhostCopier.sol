"""
Thin async SQLite data-access layer for GhostCopier.

Everything goes through a single aiosqlite connection guarded by a lock,
which is more than adequate for a paper-trading tool that is polling a
handful of wallets every few seconds.
"""
import time
import uuid
import asyncio
import aiosqlite

from .config import Config

_db: aiosqlite.Connection | None = None
_lock = asyncio.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'stopped', -- running | paused | stopped
    start_amount_usd    REAL NOT NULL,
    sol_price_at_start  REAL NOT NULL,
    start_sol_balance   REAL NOT NULL,
    sol_balance         REAL NOT NULL,
    sizing_mode         TEXT NOT NULL DEFAULT 'proportional',
    sizing_pct          REAL NOT NULL DEFAULT 10,
    slippage_pct        REAL NOT NULL DEFAULT 0.5,
    fee_pct             REAL NOT NULL DEFAULT 0.3,
    realized_pnl_usd    REAL NOT NULL DEFAULT 0,
    last_error          TEXT,
    created_at          REAL NOT NULL,
    updated_at          REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS wallets (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    address         TEXT NOT NULL,
    label           TEXT,
    active          INTEGER NOT NULL DEFAULT 1,
    last_signature  TEXT,
    added_at        REAL NOT NULL,
    UNIQUE(session_id, address)
);

CREATE TABLE IF NOT EXISTS positions (
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    token_mint      TEXT NOT NULL,
    token_symbol    TEXT,
    amount          REAL NOT NULL DEFAULT 0,
    avg_cost_sol    REAL NOT NULL DEFAULT 0,
    avg_cost_usd    REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (session_id, token_mint)
);

CREATE TABLE IF NOT EXISTS trades (
    id                          TEXT PRIMARY KEY,
    session_id                  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    tx_signature                TEXT NOT NULL,
    source_wallet                TEXT NOT NULL,
    side                        TEXT NOT NULL, -- BUY | SELL | SKIPPED
    token_mint                  TEXT NOT NULL,
    token_symbol                TEXT,
    token_amount                REAL NOT NULL,
    sol_amount                  REAL NOT NULL,
    price_usd_per_token         REAL,
    sol_price_usd               REAL,
    source_portion_pct          REAL,
    session_sol_balance_after   REAL,
    realized_pnl_usd            REAL,
    note                        TEXT,
    executed_at                 REAL NOT NULL,
    UNIQUE(session_id, tx_signature, token_mint, side)
);

CREATE INDEX IF NOT EXISTS idx_trades_session ON trades(session_id, executed_at DESC);
CREATE INDEX IF NOT EXISTS idx_wallets_session ON wallets(session_id);
"""


async def init_db():
    global _db
    _db = await aiosqlite.connect(Config.DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA foreign_keys = ON")
    await _db.executescript(SCHEMA)
    columns = await _db.execute_fetchall("PRAGMA table_info(sessions)")
    if not any(column[1] == "deposited_amount_usd" for column in columns):
        await _db.execute(
            "ALTER TABLE sessions ADD COLUMN deposited_amount_usd REAL NOT NULL DEFAULT 0"
        )
    await _db.commit()
    return _db


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        await init_db()
    return _db


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> float:
    return time.time()


# ---------------------------------------------------------------- sessions
async def create_session(name, start_amount_usd, sol_price, sizing_mode, sizing_pct,
                          slippage_pct, fee_pct):
    db = await get_db()
    sid = new_id()
    ts = now()
    sol_balance = start_amount_usd / sol_price
    async with _lock:
        await db.execute(
            """INSERT INTO sessions
               (id, name, status, start_amount_usd, sol_price_at_start,
                start_sol_balance, sol_balance, sizing_mode, sizing_pct,
                slippage_pct, fee_pct, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, name, "stopped", start_amount_usd, sol_price, sol_balance,
             sol_balance, sizing_mode, sizing_pct, slippage_pct, fee_pct, ts, ts),
        )
        await db.commit()
    return sid


async def list_sessions():
    db = await get_db()
    cur = await db.execute("SELECT * FROM sessions ORDER BY created_at DESC")
    rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_session(session_id):
    db = await get_db()
    cur = await db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def update_session_status(session_id, status):
    db = await get_db()
    async with _lock:
        await db.execute(
            "UPDATE sessions SET status = ?, updated_at = ? WHERE id = ?",
            (status, now(), session_id),
        )
        await db.commit()


async def update_session_error(session_id, message):
    db = await get_db()
    async with _lock:
        await db.execute(
            "UPDATE sessions SET last_error = ?, updated_at = ? WHERE id = ?",
            (message, now(), session_id),
        )
        await db.commit()


async def update_session_balance(session_id, sol_balance, realized_pnl_delta=0.0):
    db = await get_db()
    async with _lock:
        await db.execute(
            """UPDATE sessions
               SET sol_balance = ?, realized_pnl_usd = realized_pnl_usd + ?,
                   updated_at = ? WHERE id = ?""",
            (sol_balance, realized_pnl_delta, now(), session_id),
        )
        await db.commit()


async def top_up_session(session_id, amount_usd, sol_price):
    db = await get_db()
    sol_amount = amount_usd / sol_price
    async with _lock:
        await db.execute(
            """UPDATE sessions
               SET sol_balance = sol_balance + ?, deposited_amount_usd = deposited_amount_usd + ?,
                   updated_at = ? WHERE id = ?""",
            (sol_amount, amount_usd, now(), session_id),
        )
        await db.commit()
    return sol_amount


async def delete_session(session_id):
    db = await get_db()
    async with _lock:
        await db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        await db.commit()


# ----------------------------------------------------------------- wallets
async def add_wallet(session_id, address, label=None):
    db = await get_db()
    wid = new_id()
    async with _lock:
        await db.execute(
            """INSERT INTO wallets (id, session_id, address, label, active, added_at)
               VALUES (?,?,?,?,1,?)
               ON CONFLICT(session_id, address) DO UPDATE SET active = 1, label = excluded.label""",
            (wid, session_id, address, label, now()),
        )
        await db.commit()
    return wid


async def remove_wallet(session_id, address):
    db = await get_db()
    async with _lock:
        await db.execute(
            "DELETE FROM wallets WHERE session_id = ? AND address = ?",
            (session_id, address),
        )
        await db.commit()


async def list_wallets(session_id, active_only=False):
    db = await get_db()
    q = "SELECT * FROM wallets WHERE session_id = ?"
    if active_only:
        q += " AND active = 1"
    cur = await db.execute(q, (session_id,))
    rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def set_wallet_last_signature(wallet_id, signature):
    db = await get_db()
    async with _lock:
        await db.execute(
            "UPDATE wallets SET last_signature = ? WHERE id = ?", (signature, wallet_id)
        )
        await db.commit()


# ------------------------------------------------------------------ trades
async def insert_trade(**kwargs):
    db = await get_db()
    tid = new_id()
    kwargs["id"] = tid
    kwargs.setdefault("executed_at", now())
    cols = ",".join(kwargs.keys())
    placeholders = ",".join("?" for _ in kwargs)
    async with _lock:
        try:
            await db.execute(
                f"INSERT INTO trades ({cols}) VALUES ({placeholders})",
                tuple(kwargs.values()),
            )
            await db.commit()
        except aiosqlite.IntegrityError:
            # Already recorded (duplicate signature/token/side) - ignore.
            return None
    return tid


async def list_trades(session_id, limit=500):
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM trades WHERE session_id = ? ORDER BY executed_at DESC LIMIT ?",
        (session_id, limit),
    )
    rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def trade_exists(session_id, tx_signature, token_mint, side):
    db = await get_db()
    cur = await db.execute(
        """SELECT 1 FROM trades
           WHERE session_id = ? AND tx_signature = ? AND token_mint = ? AND side = ?""",
        (session_id, tx_signature, token_mint, side),
    )
    return await cur.fetchone() is not None


# --------------------------------------------------------------- positions
async def get_position(session_id, token_mint):
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM positions WHERE session_id = ? AND token_mint = ?",
        (session_id, token_mint),
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def list_positions(session_id, nonzero_only=True):
    db = await get_db()
    q = "SELECT * FROM positions WHERE session_id = ?"
    if nonzero_only:
        q += " AND amount > 0.00000001"
    cur = await db.execute(q, (session_id,))
    rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def upsert_position(session_id, token_mint, token_symbol, amount, avg_cost_sol, avg_cost_usd):
    db = await get_db()
    async with _lock:
        await db.execute(
            """INSERT INTO positions (session_id, token_mint, token_symbol, amount, avg_cost_sol, avg_cost_usd)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(session_id, token_mint) DO UPDATE SET
                 token_symbol = excluded.token_symbol,
                 amount = excluded.amount,
                 avg_cost_sol = excluded.avg_cost_sol,
                 avg_cost_usd = excluded.avg_cost_usd""",
            (session_id, token_mint, token_symbol, amount, avg_cost_sol, avg_cost_usd),
        )
        await db.commit()
