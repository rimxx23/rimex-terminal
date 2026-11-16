import aiohttp

from rimex.clients.common import to_decimal
from rimex.domain.models import TokenReport

SOURCE = "DexScreener"
URL = "https://api.dexscreener.com/tokens/v1/solana/{address}"


async def fetch(session: aiohttp.ClientSession, address: str) -> list:
    async with session.get(URL.format(address=address)) as response:
        response.raise_for_status()
        return await response.json()


def apply(report: TokenReport, pairs: list) -> None:
    if not pairs:
        report.errors.append("DexScreener: no pairs found")
        return
    pair = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)
    base = pair.get("baseToken", {})
    report.symbol = base.get("symbol")
    report.name = base.get("name")
    report.price_usd = to_decimal(pair.get("priceUsd"))
    report.liquidity_usd = to_decimal((pair.get("liquidity") or {}).get("usd"))
    report.volume_24h = to_decimal((pair.get("volume") or {}).get("h24"))
