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

# Base/quote currencies. These are never the asset being copy-traded -
# they're the thing being spent or received. Multihop routes (Jupiter,
# etc.) often leave a small non-zero leftover delta on these ATAs mid-swap
# (partial fills, referral skims, rounding), which can outweigh the real
# target token's delta and get misidentified as "the" trade if not
# excluded here.
QUOTE_MINTS = {
    SOL_MINT,                                        # SOL (wrapped)
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",   # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",   # USDT
    "USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB",    # USD1 (World Liberty Financial)
}


@dataclass
class SwapEvent:
    side: str            # "BUY" (SOL -> token) or "SELL" (token -> SOL)
    token_mint: str
    token_amount: float  # amount of the non-SOL token that moved
    sol_amount: float    # amount of SOL that moved (positive number)
    wallet_sol_pre: float
    wallet_token_pre: float  # source wallet's pre-trade balance of token_mint
    program_id: str | None = None  # DEX program, when present in the RPC response


def _find_account_index(account_keys, address):
    for i, key in enumerate(account_keys):
        pk = key.get("pubkey") if isinstance(key, dict) else key
        if pk == address:
            return i
    return None


def _find_program_id(message: dict) -> str | None:
    """Return the most likely DEX program ID from parsed instructions."""
    candidates = []
    for instruction in message.get("instructions", []):
        if isinstance(instruction, dict):
            program_id = instruction.get("programId")
            if program_id:
                candidates.append(program_id)
    for program_id in candidates:
        if program_id not in {
            "11111111111111111111111111111111",  # System Program
            "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",  # SPL Token
            "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",  # Associated Token
        }:
            return program_id
    return candidates[0] if candidates else None


def parse_swap_for_wallet(tx: dict, wallet_address: str) -> SwapEvent | None:
    if not tx or not tx.get("meta") or tx["meta"].get("err") is not None:
        return None  # failed tx, or nothing to parse

    meta = tx["meta"]
    message = tx["transaction"]["message"]
    account_keys = message.get("accountKeys", [])
    program_id = _find_program_id(message)

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
    # Quote/base currencies (SOL, USDC, USDT, USD1) are excluded here -
    # they're never the asset being copy-traded, and including them lets a
    # multihop route's leftover quote-currency delta get misidentified as
    # the main trade (see QUOTE_MINTS above).
    def token_map(entries):
        out = {}
        for e in entries or []:
            if e.get("owner") != wallet_address:
                continue
            mint = e.get("mint")
            if mint in QUOTE_MINTS:
                continue
            amt = e.get("uiTokenAmount", {})
            out[mint] = float(amt.get("uiAmount") or 0.0)
        return out

    pre_tokens = token_map(meta.get("preTokenBalances"))
    post_tokens = token_map(meta.get("postTokenBalances"))

    token_deltas = {}
    for mint in set(pre_tokens) | set(post_tokens):
        delta = post_tokens.get(mint, 0.0) - pre_tokens.get(mint, 0.0)
        if abs(delta) > 1e-9:
            token_deltas[mint] = delta

    if not token_deltas:
        return None  # pure SOL/stablecoin movement - not a copyable swap

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
            program_id=program_id,
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
            program_id=program_id,
        )
    return None