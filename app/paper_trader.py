"""
The paper trading engine.

Takes a detected on-chain SwapEvent from a copied wallet and simulates
the equivalent trade against a session's virtual SOL balance / token
positions, applying simulated slippage + fees, and writes a trade
record + updated position + updated balance.

Nothing here ever touches a real wallet - it is pure bookkeeping against
the numbers in the sessions/positions/trades tables.
"""
import httpx
from . import db
from .sizing import buy_portion, sell_portion
from .solana_client import get_sol_price_usd, get_token_symbol
from .config import Config

MIN_SOL_TRADE = 0.0005


async def apply_swap(session: dict, wallet_address: str, tx_signature: str, swap):
    """swap is a trade_parser.SwapEvent. Returns the inserted trade dict or None."""
    session_id = session["id"]

    if await db.trade_exists(session_id, tx_signature, swap.token_mint, swap.side):
        return None

    sol_price = await get_sol_price_usd()
    friction = (session["slippage_pct"] + session["fee_pct"]) / 100

    if swap.side == "BUY":
        return await _apply_buy(session, wallet_address, tx_signature, swap, sol_price, friction)
    else:
        return await _apply_sell(session, wallet_address, tx_signature, swap, sol_price, friction)


async def _apply_buy(session, wallet_address, tx_signature, swap, sol_price, friction):
    session_id = session["id"]
    portion = buy_portion(session, swap)
    sol_to_spend = session["sol_balance"] * portion

    if sol_to_spend < MIN_SOL_TRADE or session["sol_balance"] <= 0:
        await db.insert_trade(
            session_id=session_id, tx_signature=tx_signature, source_wallet=wallet_address,
            side="SKIPPED", token_mint=swap.token_mint,
            token_symbol=await get_token_symbol(swap.token_mint),
            token_amount=0, sol_amount=0, price_usd_per_token=None, sol_price_usd=sol_price,
            source_portion_pct=portion * 100, session_sol_balance_after=session["sol_balance"],
            realized_pnl_usd=None, note="Skipped: insufficient session balance to mirror buy",
        )
        return None

    # Effective price paid is worse than "spot" by our simulated friction.
    effective_sol_spent = sol_to_spend
    token_price_sol = swap.sol_amount / swap.token_amount if swap.token_amount else 0
    token_price_sol_effective = token_price_sol * (1 + friction)
    tokens_received = effective_sol_spent / token_price_sol_effective if token_price_sol_effective else 0

    new_balance = session["sol_balance"] - effective_sol_spent
    await db.update_session_balance(session_id, new_balance)

    pos = await db.get_position(session_id, swap.token_mint)
    prev_amount = pos["amount"] if pos else 0.0
    prev_cost_sol = pos["avg_cost_sol"] * prev_amount if pos else 0.0
    new_amount = prev_amount + tokens_received
    new_avg_cost_sol = (prev_cost_sol + effective_sol_spent) / new_amount if new_amount else 0
    new_avg_cost_usd = new_avg_cost_sol * sol_price
    symbol = await get_token_symbol(swap.token_mint)

    await db.upsert_position(session_id, swap.token_mint, symbol, new_amount, new_avg_cost_sol, new_avg_cost_usd)

    price_usd_per_token = token_price_sol_effective * sol_price
    trade_id = await db.insert_trade(
        session_id=session_id, tx_signature=tx_signature, source_wallet=wallet_address,
        side="BUY", token_mint=swap.token_mint, token_symbol=symbol,
        token_amount=tokens_received, sol_amount=effective_sol_spent,
        price_usd_per_token=price_usd_per_token, sol_price_usd=sol_price,
        source_portion_pct=portion * 100, session_sol_balance_after=new_balance,
        realized_pnl_usd=None, note=None,
    )
    return trade_id


async def _apply_sell(session, wallet_address, tx_signature, swap, sol_price, friction):
    session_id = session["id"]
    pos = await db.get_position(session_id, swap.token_mint)
    symbol = await get_token_symbol(swap.token_mint)

    if not pos or pos["amount"] <= 0:
        await db.insert_trade(
            session_id=session_id, tx_signature=tx_signature, source_wallet=wallet_address,
            side="SKIPPED", token_mint=swap.token_mint, token_symbol=symbol,
            token_amount=0, sol_amount=0, price_usd_per_token=None, sol_price_usd=sol_price,
            source_portion_pct=None, session_sol_balance_after=session["sol_balance"],
            realized_pnl_usd=None, note="Skipped: session holds no position in this token to sell",
        )
        return None

    portion = sell_portion(session, swap)
    tokens_to_sell = pos["amount"] * portion
    if tokens_to_sell <= 0:
        return None

    token_price_sol = swap.sol_amount / swap.token_amount if swap.token_amount else 0
    token_price_sol_effective = token_price_sol * (1 - friction)
    sol_received = tokens_to_sell * token_price_sol_effective

    new_balance = session["sol_balance"] + sol_received
    cost_basis_sol = pos["avg_cost_sol"] * tokens_to_sell
    realized_pnl_sol = sol_received - cost_basis_sol
    realized_pnl_usd = realized_pnl_sol * sol_price

    await db.update_session_balance(session_id, new_balance, realized_pnl_delta=realized_pnl_usd)

    remaining = pos["amount"] - tokens_to_sell
    await db.upsert_position(session_id, swap.token_mint, symbol, remaining, pos["avg_cost_sol"], pos["avg_cost_usd"])

    price_usd_per_token = token_price_sol_effective * sol_price
    trade_id = await db.insert_trade(
        session_id=session_id, tx_signature=tx_signature, source_wallet=wallet_address,
        side="SELL", token_mint=swap.token_mint, token_symbol=symbol,
        token_amount=tokens_to_sell, sol_amount=sol_received,
        price_usd_per_token=price_usd_per_token, sol_price_usd=sol_price,
        source_portion_pct=portion * 100, session_sol_balance_after=new_balance,
        realized_pnl_usd=realized_pnl_usd, note=None,
    )
    return trade_id


async def get_token_prices_usd(mints: list[str]) -> dict[str, float]:
    if not mints:
        return {}
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(
                "https://lite-api.jup.ag/price/v3",
                params={"ids": ",".join(mints)},
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                mint: info["usdPrice"]
                for mint, info in data.items()
                if info and "usdPrice" in info
            }
        except Exception as exc:
            import logging
            logging.getLogger("ghostcopier.solana_client").warning(
                "token price lookup failed: %s", exc
            )
            return {}


async def session_summary(session: dict):
    """Adds live USD valuation, unrealized PnL, and positions to a session dict."""
    sol_price = await get_sol_price_usd()
    positions = await db.list_positions(session["id"])

    mints = [p["token_mint"] for p in positions]
    live_prices = await get_token_prices_usd(mints)
    for p in positions:
        live_price = live_prices.get(p["token_mint"])
        p["market_value_usd"] = p["amount"] * live_price if live_price else p["cost_value_usd"]
        p["unrealized_pnl_usd"] = p["market_value_usd"] - p["cost_value_usd"]

    sol_balance = session["sol_balance"]
    balance_usd = sol_balance * sol_price
    holdings_value_usd = sum(p["market_value_usd"] for p in positions)
    contributed_usd = session["start_amount_usd"] + session.get("deposited_amount_usd", 0)
    total_value_usd = balance_usd + holdings_value_usd
    pnl_usd = total_value_usd - contributed_usd
    unrealized_pnl_usd = pnl_usd - session["realized_pnl_usd"]
    pnl_pct = (pnl_usd / contributed_usd * 100) if contributed_usd else 0
    unrealized_pnl_pct = (unrealized_pnl_usd / contributed_usd * 100) if contributed_usd else 0

    out = dict(session)
    out["sol_price_usd"] = sol_price
    out["balance_usd"] = balance_usd
    out["positions"] = positions
    out["contributed_amount_usd"] = contributed_usd
    out["holdings_value_usd"] = holdings_value_usd
    out["total_value_usd"] = total_value_usd
    out["pnl_usd"] = pnl_usd
    out["unrealized_pnl_usd"] = unrealized_pnl_usd
    out["unrealized_pnl_pct"] = unrealized_pnl_pct
    out["pnl_pct"] = pnl_pct
    return out
