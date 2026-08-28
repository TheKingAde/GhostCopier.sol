"""
Thin wrapper around the Solana JSON-RPC API plus a couple of public HTTP
APIs (CoinGecko for SOL/USD, Jupiter's token list for symbol lookups).

No wallet keys are ever used here - GhostCopier only ever *reads* public
chain data to observe what a wallet did; nothing is ever signed or sent.
"""
import time
import httpx

from .config import Config

SOL_MINT = "So11111111111111111111111111111111111111112"
LAMPORTS_PER_SOL = 1_000_000_000

_price_cache = {"price": None, "ts": 0}
_token_list_cache = {"map": None, "ts": 0}


class SolanaClient:
    def __init__(self, rpc_url: str | None = None):
        self.rpc_url = rpc_url or Config.SOLANA_RPC_URL
        self._client = httpx.AsyncClient(timeout=20)
        self._req_id = 0

    async def close(self):
        await self._client.aclose()

    async def _rpc(self, method: str, params: list):
        self._req_id += 1
        payload = {"jsonrpc": "2.0", "id": self._req_id, "method": method, "params": params}
        resp = await self._client.post(self.rpc_url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"RPC error on {method}: {data['error']}")
        return data.get("result")

    async def get_signatures_for_address(self, address: str, limit: int = 15, before: str | None = None):
        params = [address, {"limit": limit}]
        if before:
            params[1]["before"] = before
        result = await self._rpc("getSignaturesForAddress", params)
        return result or []

    async def get_transaction(self, signature: str):
        params = [
            signature,
            {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0, "commitment": "confirmed"},
        ]
        return await self._rpc("getTransaction", params)

    async def get_sol_balance(self, address: str) -> float:
        result = await self._rpc("getBalance", [address, {"commitment": "confirmed"}])
        if result is None:
            return 0.0
        value = result.get("value", 0) if isinstance(result, dict) else result
        return value / LAMPORTS_PER_SOL

    async def validate_address(self, address: str) -> bool:
        try:
            import base58
            decoded = base58.b58decode(address)
            return len(decoded) == 32
        except Exception:
            return False


async def get_sol_price_usd() -> float:
    """Cached SOL/USD price. Falls back to last known price on failure."""
    now = time.time()
    if _price_cache["price"] and now - _price_cache["ts"] < Config.PRICE_CACHE_TTL:
        return _price_cache["price"]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(Config.COINGECKO_PRICE_URL)
            resp.raise_for_status()
            price = resp.json()["solana"]["usd"]
            _price_cache["price"] = float(price)
            _price_cache["ts"] = now
            return _price_cache["price"]
    except Exception:
        if _price_cache["price"]:
            return _price_cache["price"]
        # Last-resort fallback so a cold start with no network still works.
        return 150.0


async def get_token_symbol(mint: str) -> str:
    """Best-effort symbol lookup via Jupiter's public token list (cached)."""
    now = time.time()
    if not _token_list_cache["map"] or now - _token_list_cache["ts"] > 3600:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(Config.JUPITER_TOKEN_LIST_URL)
                resp.raise_for_status()
                tokens = resp.json()
                _token_list_cache["map"] = {t["address"]: t.get("symbol") for t in tokens}
                _token_list_cache["ts"] = now
        except Exception:
            _token_list_cache["map"] = _token_list_cache["map"] or {}

    symbol = (_token_list_cache["map"] or {}).get(mint)
    if symbol:
        return symbol
    return mint[:4] + "…" + mint[-4:]
