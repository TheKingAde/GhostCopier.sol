import os
from dotenv import load_dotenv

load_dotenv()


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


class Config:
    SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
    POLL_INTERVAL_SECONDS = _i("POLL_INTERVAL_SECONDS", 20)
    SIGNATURE_FETCH_LIMIT = _i("SIGNATURE_FETCH_LIMIT", 15)

    DEFAULT_SLIPPAGE_PCT = _f("DEFAULT_SLIPPAGE_PCT", 0.5)
    DEFAULT_FEE_PCT = _f("DEFAULT_FEE_PCT", 0.3)

    DEFAULT_SIZING_MODE = os.getenv("DEFAULT_SIZING_MODE", "proportional")
    DEFAULT_SIZING_PCT = _f("DEFAULT_SIZING_PCT", 10)

    PRICE_CACHE_TTL = _i("PRICE_CACHE_TTL", 30)

    DB_PATH = os.getenv("DB_PATH", "ghostcopier.db")

    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = _i("PORT", 5000)

    # Minimum USD notional for a detected swap to be considered a real trade
    # (filters dust / rounding noise out of the copy engine).
    MIN_TRADE_USD = _f("MIN_TRADE_USD", 1.0)

    JUPITER_TOKEN_LIST_URL = "https://token.jup.ag/all"
    COINGECKO_PRICE_URL = (
        "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
    )
