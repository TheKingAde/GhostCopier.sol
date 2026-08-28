"""
Position sizing strategies.

Given a swap made by the wallet we're copying, decide how much of the
*session's* virtual SOL (or token position, for a sell) to commit.
"""


def buy_portion(session: dict, swap) -> float:
    """Returns the fraction (0-1] of the session's SOL balance to spend on a BUY."""
    mode = session["sizing_mode"]
    if mode == "fixed_pct":
        return max(0.0, min(1.0, session["sizing_pct"] / 100))

    # proportional: mirror the % of their own pre-trade SOL balance they spent
    if swap.wallet_sol_pre <= 0:
        return 0.0
    portion = swap.sol_amount / swap.wallet_sol_pre
    return max(0.0, min(1.0, portion))


def sell_portion(session: dict, swap) -> float:
    """Returns the fraction (0-1] of the session's *token position* to sell."""
    mode = session["sizing_mode"]
    if mode == "fixed_pct":
        return max(0.0, min(1.0, session["sizing_pct"] / 100))

    if swap.wallet_token_pre <= 0:
        return 1.0  # they dumped their whole bag and we have no better reference - mirror fully
    portion = swap.token_amount / swap.wallet_token_pre
    return max(0.0, min(1.0, portion))
