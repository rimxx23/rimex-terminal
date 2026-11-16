import time

import aiohttp

from rimex.clients.common import to_decimal
from rimex.domain.models import TokenReport

URL = "https://api.rugcheck.xyz/v1/tokens/{address}/report/summary"
TIMEOUT = aiohttp.ClientTimeout(total=1.5)
CACHE_TTL = 300

_cache: dict[str, tuple[float, dict]] = {}


async def fetch(session: aiohttp.ClientSession, address: str) -> dict:
    cached = _cache.get(address)
    if cached and time.monotonic() - cached[0] < CACHE_TTL:
        return cached[1]
    async with session.get(URL.format(address=address), timeout=TIMEOUT) as response:
        response.raise_for_status()
        data = await response.json()
    _cache[address] = (time.monotonic(), data)
    return data


def apply(report: TokenReport, data: dict) -> None:
    report.risk_score = data.get("score_normalised")
    report.lp_locked_pct = to_decimal(data.get("lpLockedPct"))
    report.risks = [risk["name"] for risk in data.get("risks") or []]
