import base58


def is_valid_solana_address(address: str) -> bool:
    if not address or not (32 <= len(address) <= 44):
        return False
    try:
        decoded = base58.b58decode(address)
        return len(decoded) == 32
    except Exception:
        return False


def clean_wallet_list(raw) -> list[str]:
    """Accepts a list, or a newline/comma separated string, of addresses."""
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.replace(",", "\n").split("\n")]
    else:
        parts = [str(p).strip() for p in raw]
    seen = set()
    out = []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out
