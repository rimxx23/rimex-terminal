import re

SOLANA_ADDRESS_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def is_valid_address(address: str) -> bool:
    return bool(SOLANA_ADDRESS_RE.match(address))


def short_address(address: str) -> str:
    return f"{address[:4]}…{address[-4:]}"
