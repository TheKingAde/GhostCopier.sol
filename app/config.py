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

    # Real-world friction defaults (increased from unrealistic 0.5% + 0.3%)
    DEFAULT_SLIPPAGE_PCT = _f("DEFAULT_SLIPPAGE_PCT", 1.5)  # 1.5% base slippage
    DEFAULT_FEE_PCT = _f("DEFAULT_FEE_PCT", 0.5)  # 0.5% DEX fees

    DEFAULT_SIZING_MODE = os.getenv("DEFAULT_SIZING_MODE", "proportional")
    DEFAULT_SIZING_PCT = _f("DEFAULT_SIZING_PCT", 10)

    PRICE_CACHE_TTL = _i("PRICE_CACHE_TTL", 30)

    DB_PATH = os.getenv("DB_PATH", "ghostcopier.db")

    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = _i("PORT", 5000)

    # Minimum USD notional for a detected swap to be considered a real trade
    # (filters dust / rounding noise out of the copy engine).
    MIN_TRADE_USD = _f("MIN_TRADE_USD", 1.0)

    # Price service configuration
    JUPITER_TOKEN_LIST_URL = "https://token.jup.ag/all"
    COINGECKO_PRICE_URL = (
        "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
    )
    
    # Birdeye API for live token prices
    BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY", "")
    BIRDEYE_PRICE_URL = "https://public-api.birdeye.so/defi/token_price"
    
    # Price history limit for volatility calculations
    PRICE_HISTORY_LIMIT = _i("PRICE_HISTORY_LIMIT", 100)
    
    # Network fee (SOL) - typical value
    NETWORK_FEE_SOL = _f("NETWORK_FEE_SOL", 0.00025)
    
    # Dynamic slippage: extra % per $1000 of swap value
    SLIPPAGE_PER_1K_USD = _f("SLIPPAGE_PER_1K_USD", 0.1)
    
    # Maximum slippage cap (prevents runaway friction)
    MAX_SLIPPAGE_PCT = _f("MAX_SLIPPAGE_PCT", 10.0)
    
    # MEV/sandwich risk: probability of swap failure
    MEV_FAILURE_PROBABILITY = _f("MEV_FAILURE_PROBABILITY", 0.02)
