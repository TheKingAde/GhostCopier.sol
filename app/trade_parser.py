"""
Heuristic swap detector.

Real Solana swaps go through many different programs (Jupiter, Raydium,
Orca, Pump.fun, ...). Rather than special-case every program's
instruction layout, we look at the *net effect* on the wallet we're
watching: compare its pre/post SOL balance and pre/post SPL token
balances for the transaction. A swap shows up as "one side of the
ledger went down, the other went up", regardless of which DEX routed it.

This intentionally ignores plain transfers (only one side changes,
nothing received in exchange) and only fires for genuine buy/sell swaps.
"""
from dataclasses import dataclass
from .solana_client import SOL_MINT, LAMPORTS_PER_SOL

DUST_SOL = 0.0005  # ignore SOL deltas below this (fees/rent noise)


@dataclass
class SwapEvent:
    side: str            # "BUY" (SOL -> token) or "SELL" (token -> SOL)
    token_mint: str
    token_amount: float  # amount of the non-SOL token that moved
    sol_amount: float    # amount of SOL that moved (positive number)
    wallet_sol_pre: float
    wallet_token_pre: float  # source wallet's pre-trade balance of token_mint


def _find_account_index(account_keys, address):
    for i, key in enumerate(account_keys):
        pk = key.get("pubkey") if isinstance(key, dict) else key
        if pk == address:
            return i
    return None


def parse_swap_for_wallet(tx: dict, wallet_address: str) -> SwapEvent | None:
    if not tx or not tx.get("meta") or tx["meta"].get("err") is not None:
        return None  # failed tx, or nothing to parse

    meta = tx["meta"]
    message = tx["transaction"]["message"]
    account_keys = message.get("accountKeys", [])

    idx = _find_account_index(account_keys, wallet_address)
    if idx is None:
        return None

    pre_balances = meta.get("preBalances", [])
    post_balances = meta.get("postBalances", [])
    if idx >= len(pre_balances) or idx >= len(post_balances):
        return None

    sol_delta = (post_balances[idx] - pre_balances[idx]) / LAMPORTS_PER_SOL
    wallet_sol_pre = pre_balances[idx] / LAMPORTS_PER_SOL

    # Build pre/post SPL token balance maps for this wallet: mint -> amount
    def token_map(entries):
        out = {}
        for e in entries or []:
            if e.get("owner") != wallet_address:
                continue
            amt = e.get("uiTokenAmount", {})
            out[e["mint"]] = float(amt.get("uiAmount") or 0.0)
        return out

    pre_tokens = token_map(meta.get("preTokenBalances"))
    post_tokens = token_map(meta.get("postTokenBalances"))

    token_deltas = {}
    for mint in set(pre_tokens) | set(post_tokens):
        delta = post_tokens.get(mint, 0.0) - pre_tokens.get(mint, 0.0)
        if abs(delta) > 1e-9:
            token_deltas[mint] = delta

    if not token_deltas:
        return None  # pure SOL transfer, staking, etc - not a swap

    # Pick the token whose magnitude of change is largest (main leg of the swap)
    main_mint = max(token_deltas, key=lambda m: abs(token_deltas[m]))
    token_delta = token_deltas[main_mint]

    if abs(sol_delta) < DUST_SOL:
        # No meaningful SOL movement -> likely a token/token swap or an
        # airdrop, not something we can price against SOL confidently.
        return None

    if sol_delta < 0 and token_delta > 0:
        # Spent SOL, received token => BUY
        return SwapEvent(
            side="BUY",
            token_mint=main_mint,
            token_amount=token_delta,
            sol_amount=abs(sol_delta),
            wallet_sol_pre=wallet_sol_pre,
            wallet_token_pre=pre_tokens.get(main_mint, 0.0),
        )
    if sol_delta > 0 and token_delta < 0:
        # Sold token, received SOL => SELL
        return SwapEvent(
            side="SELL",
            token_mint=main_mint,
            token_amount=abs(token_delta),
            sol_amount=sol_delta,
            wallet_sol_pre=wallet_sol_pre,
            wallet_token_pre=pre_tokens.get(main_mint, 0.0),
        )
    return None
