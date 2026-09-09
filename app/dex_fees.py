"""DEX fee and trade-size slippage estimates for paper trading."""

from .config import Config


SOLANA_NETWORK_FEE_SOL = Config.NETWORK_FEE_SOL

# Common Solana swap programs. Unknown programs use the configured default.
_DEX_FEE_BPS = {
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZ6wD6K6G8j": 0,
    "675kPX9MHTjS2zt1qfr1NYHuze8m8B5WfYh8h5f2b": 25,
    "whirLbMiicVdio4qvUfM5KAg6Ct8qL2NfH9uKj4d": 30,
    "6EF8rrecthR5Dkzon8Nwu78kRmt9FfN7rFf7X2Y": 100,
}


def get_dex_fee_bps(program_id: str | None) -> float:
    """Return the estimated DEX fee in basis points for a swap program."""
    if program_id in _DEX_FEE_BPS:
        return _DEX_FEE_BPS[program_id]
    return Config.DEFAULT_FEE_PCT * 100


class DynamicSlippage:
    """Estimate slippage from the trade's USD notional and base setting."""

    @staticmethod
    def estimate_slippage_pct(
        sol_amount: float,
        token_amount: float,
        pool_sol_liquidity: float | None,
        is_buy: bool,
        base_slippage_pct: float,
    ) -> float:
        del token_amount, is_buy

        if pool_sol_liquidity and pool_sol_liquidity > 0:
            liquidity_ratio = sol_amount / pool_sol_liquidity
            liquidity_impact_pct = liquidity_ratio * 100
        else:
            liquidity_impact_pct = 0.0

        size_impact_pct = 0.0
        # The caller supplies SOL, while Config's heuristic is denominated in
        # USD. Use a modest SOL/USD-independent fallback for missing pool data.
        if not pool_sol_liquidity:
            size_impact_pct = Config.SLIPPAGE_PER_1K_USD * min(sol_amount * 200 / 1000, 10)

        return min(
            base_slippage_pct + liquidity_impact_pct + size_impact_pct,
            Config.MAX_SLIPPAGE_PCT,
        )