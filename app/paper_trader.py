"""
The paper trading engine.

Takes a detected on-chain SwapEvent from a copied wallet and simulates
the equivalent trade against a session's virtual SOL balance / token
positions, applying realistic slippage + DEX fees + dynamic trade-size
impact, and writes a trade record + updated position + updated balance.

Real-world enhancements:
- Dynamic slippage based on trade size
- DEX-specific fee structures
- Live token price feeds for accurate unrealized PnL
- MEV/sandwich attack simulation
- Volatility-based position valuation

Nothing here ever touches a real wallet - it is pure bookkeeping against
the numbers in the sessions/positions/trades tables.
"""
import random
import logging
from . import db
from .sizing import buy_portion, sell_portion
from .solana_client import get_sol_price_usd, get_token_symbol
from .price_service import get_token_price_usd, get_price_service
from .dex_fees import DynamicSlippage, get_dex_fee_bps, SOLANA_NETWORK_FEE_SOL
from .config import Config

logger = logging.getLogger(__name__)
MIN_SOL_TRADE = 0.0005


async def apply_swap(session: dict, wallet_address: str, tx_signature: str, swap):
    """
    Apply a detected swap to a session's paper portfolio.
    
    swap is a trade_parser.SwapEvent. 
    Returns the inserted trade dict or None.
    """
    session_id = session["id"]

    if await db.trade_exists(session_id, tx_signature, swap.token_mint, swap.side):
        return None

    # Simulate MEV/sandwich attacks: ~2% of swaps fail
    if random.random() < Config.MEV_FAILURE_PROBABILITY:
        sol_price = await get_sol_price_usd()
        await db.insert_trade(
            session_id=session_id, tx_signature=tx_signature, source_wallet=wallet_address,
            side="SKIPPED", token_mint=swap.token_mint,
            token_symbol=await get_token_symbol(swap.token_mint),
            token_amount=0, sol_amount=0, price_usd_per_token=None, sol_price_usd=sol_price,
            source_portion_pct=None, session_sol_balance_after=session["sol_balance"],
            realized_pnl_usd=None, note="Skipped: MEV/sandwich attack (simulated failed swap)",
        )
        logger.info(f"Simulated MEV failure for tx {tx_signature}")
        return None

    sol_price = await get_sol_price_usd()
    
    # Get DEX-specific fees (in basis points)
    dex_fee_bps = get_dex_fee_bps(swap.program_id)
    dex_fee_pct = dex_fee_bps / 100  # Convert basis points to percentage
    
    # Use session slippage as base, will be enhanced with dynamic calculation
    base_slippage_pct = session["slippage_pct"]
    
    if swap.side == "BUY":
        return await _apply_buy(session, wallet_address, tx_signature, swap, sol_price, base_slippage_pct, dex_fee_pct)
    else:
        return await _apply_sell(session, wallet_address, tx_signature, swap, sol_price, base_slippage_pct, dex_fee_pct)


async def _apply_buy(session, wallet_address, tx_signature, swap, sol_price, base_slippage_pct, dex_fee_pct):
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

    # Calculate dynamic slippage based on trade size
    sol_notional_usd = sol_to_spend * sol_price
    dynamic_slippage_pct = DynamicSlippage.estimate_slippage_pct(
        sol_amount=sol_to_spend,
        token_amount=swap.token_amount,
        pool_sol_liquidity=None,  # Will use heuristic
        is_buy=True,
        base_slippage_pct=base_slippage_pct,
    )
    
    # Total friction = dynamic slippage + DEX fees + network fee impact
    total_slippage_pct = min(dynamic_slippage_pct, Config.MAX_SLIPPAGE_PCT)
    total_friction_pct = total_slippage_pct + dex_fee_pct
    total_friction = total_friction_pct / 100

    # Effective price paid is worse than "spot" by our simulated friction
    effective_sol_spent = sol_to_spend
    token_price_sol = swap.sol_amount / swap.token_amount if swap.token_amount else 0
    token_price_sol_effective = token_price_sol * (1 + total_friction)
    tokens_received = effective_sol_spent / token_price_sol_effective if token_price_sol_effective else 0

    # Subtract network fee from balance
    new_balance = session["sol_balance"] - effective_sol_spent - SOLANA_NETWORK_FEE_SOL
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
        realized_pnl_usd=None, note=f"Slippage: {total_slippage_pct:.2f}% + DEX fee: {dex_fee_pct:.2f}%",
    )
    return trade_id


async def _apply_sell(session, wallet_address, tx_signature, swap, sol_price, base_slippage_pct, dex_fee_pct):
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

    # Calculate dynamic slippage based on trade size
    token_price_sol = swap.sol_amount / swap.token_amount if swap.token_amount else 0
    sol_notional = tokens_to_sell * token_price_sol
    sol_notional_usd = sol_notional * sol_price
    
    dynamic_slippage_pct = DynamicSlippage.estimate_slippage_pct(
        sol_amount=sol_notional,
        token_amount=tokens_to_sell,
        pool_sol_liquidity=None,  # Will use heuristic
        is_buy=False,
        base_slippage_pct=base_slippage_pct,
    )
    
    # Total friction = dynamic slippage + DEX fees
    total_slippage_pct = min(dynamic_slippage_pct, Config.MAX_SLIPPAGE_PCT)
    total_friction_pct = total_slippage_pct + dex_fee_pct
    total_friction = total_friction_pct / 100

    token_price_sol_effective = token_price_sol * (1 - total_friction)
    sol_received = tokens_to_sell * token_price_sol_effective

    new_balance = session["sol_balance"] + sol_received - SOLANA_NETWORK_FEE_SOL
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
        realized_pnl_usd=realized_pnl_usd, note=f"Slippage: {total_slippage_pct:.2f}% + DEX fee: {dex_fee_pct:.2f}%",
    )
    return trade_id


async def session_summary(session: dict):
    """
    Builds a comprehensive session summary with live pricing and accurate unrealized PnL.
    
    Real-world enhancements:
    - Uses live token prices from Birdeye API (if available)
    - Calculates true unrealized PnL = (market_price - cost_basis) * amount
    - Includes price volatility indicators
    - Marks positions with unknown prices as 'pending'
    """
    sol_price = await get_sol_price_usd()
    positions = await db.list_positions(session["id"])
    price_service = get_price_service()

    total_holdings_value_usd = 0.0
    total_unrealized_pnl_usd = 0.0
    unknown_price_positions = []

    for p in positions:
        # Try to get live price from Birdeye API
        token_price_usd = await get_token_price_usd(p["token_mint"])
        
        if token_price_usd and token_price_usd > 0:
            # Live price available - calculate true unrealized PnL
            p["current_price_usd"] = token_price_usd
            p["market_value_usd"] = p["amount"] * token_price_usd
            
            # Unrealized PnL = (current_price - cost_basis) * amount
            cost_basis_usd = p["avg_cost_usd"]
            p["unrealized_pnl_usd"] = (token_price_usd - cost_basis_usd) * p["amount"]
            p["unrealized_pnl_pct"] = ((token_price_usd - cost_basis_usd) / cost_basis_usd * 100) if cost_basis_usd > 0 else 0
            
            # Include volatility tier for risk assessment
            volatility = price_service.get_price_volatility(p["token_mint"])
            if volatility < 0.05:
                p["liquidity_tier"] = "high"
            elif volatility < 0.20:
                p["liquidity_tier"] = "medium"
            else:
                p["liquidity_tier"] = "low"
            
            total_holdings_value_usd += p["market_value_usd"]
            total_unrealized_pnl_usd += p["unrealized_pnl_usd"]
        else:
            # No live price - fall back to cost basis (conservative estimate)
            p["current_price_usd"] = None
            p["market_value_usd"] = p["amount"] * p["avg_cost_usd"]
            p["unrealized_pnl_usd"] = 0.0  # Mark as unknown
            p["unrealized_pnl_pct"] = 0.0
            p["liquidity_tier"] = "unknown"
            p["price_status"] = "pending"  # Signal that price data is unavailable
            unknown_price_positions.append(p["token_mint"])
            
            total_holdings_value_usd += p["market_value_usd"]

    sol_balance = session["sol_balance"]
    balance_usd = sol_balance * sol_price
    
    contributed_usd = session["start_amount_usd"] + session.get("deposited_amount_usd", 0)
    total_value_usd = balance_usd + total_holdings_value_usd
    
    # Realized PnL from completed sells
    realized_pnl_usd = session["realized_pnl_usd"]
    
    # Total PnL = realized + unrealized
    total_pnl_usd = realized_pnl_usd + total_unrealized_pnl_usd
    
    total_pnl_pct = (total_pnl_usd / contributed_usd * 100) if contributed_usd else 0
    unrealized_pnl_pct = (total_unrealized_pnl_usd / contributed_usd * 100) if contributed_usd else 0
    realized_pnl_pct = (realized_pnl_usd / contributed_usd * 100) if contributed_usd else 0

    out = dict(session)
    out["sol_price_usd"] = sol_price
    out["balance_usd"] = balance_usd
    out["positions"] = positions
    out["contributed_amount_usd"] = contributed_usd
    out["holdings_value_usd"] = total_holdings_value_usd
    out["total_value_usd"] = total_value_usd
    out["realized_pnl_usd"] = realized_pnl_usd
    out["realized_pnl_pct"] = realized_pnl_pct
    out["unrealized_pnl_usd"] = total_unrealized_pnl_usd
    out["unrealized_pnl_pct"] = unrealized_pnl_pct
    out["pnl_usd"] = total_pnl_usd
    out["pnl_pct"] = total_pnl_pct
    out["unknown_price_positions"] = unknown_price_positions
    out["price_data_complete"] = len(unknown_price_positions) == 0
    
    return out
