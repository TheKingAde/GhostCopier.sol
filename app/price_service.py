import time
import httpx
import logging
from collections import defaultdict
from .config import Config

logger = logging.getLogger(__name__)

# Per-token price history: mint -> [{"price": float, "ts": float}, ...]
_price_history = defaultdict(list)
_sol_price_cache = {"price": None, "ts": 0}


class PriceService:
    """Handles all price data: SOL, tokens, caching, volatility."""

    # Jupiter's free tier host. No API key required, ~60 req/min.
    # For higher throughput, switch to https://api.jup.ag and add an
    # "x-api-key" header (see Config.JUPITER_API_KEY).
    JUPITER_PRICE_URL = "https://lite-api.jup.ag/price/v3"

    def __init__(self):
        self._client = httpx.AsyncClient(timeout=10)

    async def close(self):
        await self._client.aclose()

    async def get_sol_price_usd(self) -> float:
        """Get SOL/USD price with caching."""
        now = time.time()
        if _sol_price_cache["price"] and now - _sol_price_cache["ts"] < Config.PRICE_CACHE_TTL:
            return _sol_price_cache["price"]

        try:
            resp = await self._client.get(Config.COINGECKO_PRICE_URL)
            resp.raise_for_status()
            price = resp.json()["solana"]["usd"]
            _sol_price_cache["price"] = float(price)
            _sol_price_cache["ts"] = now
            return _sol_price_cache["price"]
        except Exception as e:
            logger.warning(f"Failed to fetch SOL price: {e}")
            if _sol_price_cache["price"]:
                return _sol_price_cache["price"]
            return 150.0  # Fallback

    async def get_token_price_usd(self, mint: str) -> float | None:
        """
        Get token price in USD via Jupiter's Price API (free lite-api tier).
        Falls back to last cached price if unavailable.
        Returns None if no data available.
        """
        try:
            headers = {}
            if getattr(Config, "JUPITER_API_KEY", None):
                # If you upgrade to a paid Jupiter tier, this switches you
                # onto the higher-throughput api.jup.ag host automatically
                # is NOT automatic — set Config.JUPITER_PRICE_URL to
                # "https://api.jup.ag/price/v3" as well if you add a key.
                headers["x-api-key"] = Config.JUPITER_API_KEY

            resp = await self._client.get(
                self.JUPITER_PRICE_URL,
                params={"ids": mint},
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                token_data = data.get(mint)
                if token_data and "usdPrice" in token_data:
                    price_usd = float(token_data["usdPrice"])
                    if price_usd > 0:
                        self._record_price(mint, price_usd)
                        return price_usd
            elif resp.status_code == 429:
                logger.debug(f"Jupiter Price API rate limited for {mint}")
        except Exception as e:
            logger.debug(f"Failed to fetch token price for {mint}: {e}")

        # Fall back to last cached price
        if mint in _price_history and _price_history[mint]:
            return _price_history[mint][-1]["price"]

        return None

    def _record_price(self, mint: str, price_usd: float):
        """Record price in history for volatility/trend analysis."""
        now = time.time()
        _price_history[mint].append({"price": price_usd, "ts": now})

        # Keep only recent history
        if len(_price_history[mint]) > Config.PRICE_HISTORY_LIMIT:
            _price_history[mint] = _price_history[mint][-Config.PRICE_HISTORY_LIMIT:]

    def get_price_volatility(self, mint: str) -> float:
        """
        Calculate 24h price volatility (std dev of returns).
        Returns 0 if insufficient data.
        """
        if mint not in _price_history or len(_price_history[mint]) < 2:
            return 0.0

        prices = [p["price"] for p in _price_history[mint]]
        if any(p <= 0 for p in prices):
            return 0.0

        # Simple return calculation
        returns = []
        for i in range(1, len(prices)):
            ret = (prices[i] - prices[i - 1]) / prices[i - 1]
            returns.append(ret)

        if not returns:
            return 0.0

        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
        volatility = variance ** 0.5
        return volatility

    def estimate_token_liquidity_tier(self, mint: str) -> str:
        """
        Estimate token liquidity tier based on price stability.
        High volatility = low liquidity = shitcoin.
        """
        volatility = self.get_price_volatility(mint)

        if volatility < 0.05:
            return "high"
        elif volatility < 0.20:
            return "medium"
        else:
            return "low"


# Global singleton
_price_service = PriceService()


async def get_sol_price_usd() -> float:
    """Global helper for SOL price."""
    return await _price_service.get_sol_price_usd()


async def get_token_price_usd(mint: str) -> float | None:
    """Global helper for token price."""
    return await _price_service.get_token_price_usd(mint)


def get_price_service() -> PriceService:
    """Get the global price service."""
    return _price_service
