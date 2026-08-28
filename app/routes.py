from quart import Blueprint, render_template, jsonify, request, abort

from . import db
from . import monitor
from . import paper_trader
from .solana_client import get_sol_price_usd, SolanaClient
from .utils import is_valid_solana_address, clean_wallet_list
from .config import Config

bp = Blueprint("main", __name__)


# --------------------------------------------------------------- pages
@bp.get("/")
async def index():
    return await render_template("index.html")


@bp.get("/session/<session_id>")
async def session_page(session_id):
    session = await db.get_session(session_id)
    if not session:
        abort(404)
    return await render_template("session.html", session=session)


# ------------------------------------------------------------ misc API
@bp.get("/api/sol-price")
async def api_sol_price():
    price = await get_sol_price_usd()
    return jsonify({"sol_usd": price})


@bp.post("/api/validate-address")
async def api_validate_address():
    data = await request.get_json(force=True, silent=True) or {}
    address = (data.get("address") or "").strip()
    return jsonify({"address": address, "valid": is_valid_solana_address(address)})


# --------------------------------------------------------- sessions API
@bp.get("/api/sessions")
async def api_list_sessions():
    sessions = await db.list_sessions()
    out = []
    for s in sessions:
        wallets = await db.list_wallets(s["id"])
        trades = await db.list_trades(s["id"], limit=1)
        summary = await paper_trader.session_summary(s)
        summary["wallet_count"] = len(wallets)
        summary["is_running"] = monitor.is_running(s["id"])
        summary["last_trade_at"] = trades[0]["executed_at"] if trades else None
        out.append(summary)
    return jsonify(out)


@bp.post("/api/sessions")
async def api_create_session():
    data = await request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip() or "Untitled session"
    try:
        start_amount_usd = float(data.get("start_amount_usd"))
    except (TypeError, ValueError):
        return jsonify({"error": "start_amount_usd must be a number"}), 400
    if start_amount_usd <= 0:
        return jsonify({"error": "start_amount_usd must be greater than 0"}), 400

    wallets = clean_wallet_list(data.get("wallets"))
    if not wallets:
        return jsonify({"error": "At least one wallet address is required"}), 400

    invalid = [w for w in wallets if not is_valid_solana_address(w)]
    if invalid:
        return jsonify({"error": "Invalid Solana address(es)", "addresses": invalid}), 400

    sizing_mode = data.get("sizing_mode") or Config.DEFAULT_SIZING_MODE
    if sizing_mode not in ("proportional", "fixed_pct"):
        sizing_mode = Config.DEFAULT_SIZING_MODE
    sizing_pct = float(data.get("sizing_pct") or Config.DEFAULT_SIZING_PCT)
    slippage_pct = float(data.get("slippage_pct") or Config.DEFAULT_SLIPPAGE_PCT)
    fee_pct = float(data.get("fee_pct") or Config.DEFAULT_FEE_PCT)

    sol_price = await get_sol_price_usd()
    session_id = await db.create_session(
        name, start_amount_usd, sol_price, sizing_mode, sizing_pct, slippage_pct, fee_pct
    )
    for addr in wallets:
        await db.add_wallet(session_id, addr)

    autostart = bool(data.get("autostart", True))
    if autostart:
        await monitor.start_session(session_id)

    session = await db.get_session(session_id)
    summary = await paper_trader.session_summary(session)
    return jsonify(summary), 201


@bp.get("/api/sessions/<session_id>")
async def api_get_session(session_id):
    session = await db.get_session(session_id)
    if not session:
        abort(404)
    summary = await paper_trader.session_summary(session)
    summary["wallets"] = await db.list_wallets(session_id)
    summary["is_running"] = monitor.is_running(session_id)
    return jsonify(summary)


@bp.delete("/api/sessions/<session_id>")
async def api_delete_session(session_id):
    session = await db.get_session(session_id)
    if not session:
        abort(404)
    await monitor.stop_session(session_id)
    await db.delete_session(session_id)
    return jsonify({"ok": True})


@bp.post("/api/sessions/<session_id>/start")
async def api_start_session(session_id):
    session = await db.get_session(session_id)
    if not session:
        abort(404)
    await monitor.start_session(session_id)
    return jsonify({"ok": True, "status": "running"})


@bp.post("/api/sessions/<session_id>/pause")
async def api_pause_session(session_id):
    session = await db.get_session(session_id)
    if not session:
        abort(404)
    await monitor.pause_session(session_id)
    return jsonify({"ok": True, "status": "paused"})


@bp.post("/api/sessions/<session_id>/stop")
async def api_stop_session(session_id):
    session = await db.get_session(session_id)
    if not session:
        abort(404)
    await monitor.stop_session(session_id)
    return jsonify({"ok": True, "status": "stopped"})


# ----------------------------------------------------------- wallets API
@bp.get("/api/sessions/<session_id>/wallets")
async def api_list_wallets(session_id):
    if not await db.get_session(session_id):
        abort(404)
    return jsonify(await db.list_wallets(session_id))


@bp.post("/api/sessions/<session_id>/wallets")
async def api_add_wallet(session_id):
    if not await db.get_session(session_id):
        abort(404)
    data = await request.get_json(force=True, silent=True) or {}
    address = (data.get("address") or "").strip()
    label = (data.get("label") or "").strip() or None
    if not is_valid_solana_address(address):
        return jsonify({"error": "Invalid Solana address"}), 400
    await db.add_wallet(session_id, address, label)
    return jsonify(await db.list_wallets(session_id)), 201


@bp.delete("/api/sessions/<session_id>/wallets/<address>")
async def api_remove_wallet(session_id, address):
    if not await db.get_session(session_id):
        abort(404)
    await db.remove_wallet(session_id, address)
    return jsonify(await db.list_wallets(session_id))


# ------------------------------------------------------------ trades API
@bp.get("/api/sessions/<session_id>/trades")
async def api_list_trades(session_id):
    if not await db.get_session(session_id):
        abort(404)
    limit = int(request.args.get("limit", 500))
    return jsonify(await db.list_trades(session_id, limit=limit))


@bp.get("/api/sessions/<session_id>/positions")
async def api_list_positions(session_id):
    if not await db.get_session(session_id):
        abort(404)
    return jsonify(await db.list_positions(session_id))
