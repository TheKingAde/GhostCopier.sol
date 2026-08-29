"""
Background monitor: one asyncio task per running session, polling every
watched wallet for new signatures and feeding detected swaps into the
paper trading engine.
"""
import asyncio
import logging

from . import db
from . import paper_trader
from .solana_client import SolanaClient
from .trade_parser import parse_swap_for_wallet
from .config import Config

log = logging.getLogger("ghostcopier.monitor")
logging.getLogger("httpx").setLevel(logging.WARNING)

_tasks: dict[str, asyncio.Task] = {}
_clients: dict[str, SolanaClient] = {}


def is_running(session_id: str) -> bool:
    task = _tasks.get(session_id)
    return bool(task and not task.done())


async def start_session(session_id: str):
    if is_running(session_id):
        return
    await db.update_session_status(session_id, "running")
    client = SolanaClient()
    _clients[session_id] = client
    task = asyncio.create_task(_run_loop(session_id, client), name=f"monitor-{session_id}")
    _tasks[session_id] = task


async def pause_session(session_id: str):
    await db.update_session_status(session_id, "paused")
    await _stop_task(session_id)


async def stop_session(session_id: str):
    await db.update_session_status(session_id, "stopped")
    await _stop_task(session_id)


async def _stop_task(session_id: str):
    task = _tasks.pop(session_id, None)
    if task and not task.done():
        task.cancel()
    client = _clients.pop(session_id, None)
    if client:
        await client.close()


async def bootstrap_running_sessions():
    """Called on app startup: resume any session that was left in 'running' state."""
    sessions = await db.list_sessions()
    for s in sessions:
        if s["status"] == "running":
            await start_session(s["id"])


async def _run_loop(session_id: str, client: SolanaClient):
    log.info("monitor started for session %s", session_id)
    try:
        while True:
            session = await db.get_session(session_id)
            if not session or session["status"] != "running":
                return

            try:
                await _poll_once(session, client)
                await db.update_session_error(session_id, None)
            except Exception as exc:  # keep the loop alive across transient RPC errors
                log.warning("poll error for session %s: %s", session_id, exc)
                await db.update_session_error(session_id, str(exc))

            await asyncio.sleep(Config.POLL_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        log.info("monitor stopped for session %s", session_id)
        raise


async def _poll_once(session: dict, client: SolanaClient):
    wallets = await db.list_wallets(session["id"], active_only=True)
    for wallet in wallets:
        try:
            await _poll_wallet(session, wallet, client)
        except Exception as exc:
            log.warning("wallet poll failed %s: %s", wallet["address"], exc)
            raise

async def _poll_wallet(session: dict, wallet: dict, client: SolanaClient):
    signatures = await client.get_signatures_for_address(
        wallet["address"], limit=Config.SIGNATURE_FETCH_LIMIT
    )
    if not signatures:
        return

    last_seen = wallet.get("last_signature")
    # RPC returns newest-first; only process what's new, oldest-first so
    # trade history reads chronologically.
    new_sigs = []
    for sig_info in signatures:
        if sig_info.get("signature") == last_seen:
            break
        new_sigs.append(sig_info)
    new_sigs.reverse()

    if not new_sigs:
        return

    for sig_info in new_sigs:
        signature = sig_info["signature"]
        if sig_info.get("err"):
            continue
        try:
            tx = await client.get_transaction(signature)
        except Exception as exc:
            log.warning("failed to fetch tx %s: %s", signature, exc)
            continue

        swap = parse_swap_for_wallet(tx, wallet["address"])
        if swap:
            # re-fetch session each iteration: balance may have changed
            # from a prior swap earlier in this same batch
            fresh_session = await db.get_session(session["id"])
            if fresh_session and fresh_session["status"] == "running":
                await paper_trader.apply_swap(fresh_session, wallet["address"], signature, swap)

    await db.set_wallet_last_signature(wallet["id"], new_sigs[-1]["signature"])
