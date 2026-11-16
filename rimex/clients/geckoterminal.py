from decimal import Decimal

import aiohttp

from rimex.clients.common import to_decimal
from rimex.domain.models import TokenReport

SOURCE = "GeckoTerminal"
TOKEN_URL = "https://api.geckoterminal.com/api/v2/networks/solana/tokens/{address}"
INFO_URL = TOKEN_URL + "/info"


async def _get_json(session: aiohttp.ClientSession, url: str) -> dict:
    async with session.get(url, headers={"Accept": "application/json"}) as response:
        response.raise_for_status()
        return await response.json()


async def fetch_token(session: aiohttp.ClientSession, address: str) -> dict:
    return await _get_json(session, TOKEN_URL.format(address=address))


async def fetch_info(session: aiohttp.ClientSession, address: str) -> dict:
    return await _get_json(session, INFO_URL.format(address=address))


def _attributes(data: dict) -> dict:
    return ((data or {}).get("data") or {}).get("attributes") or {}


def apply_token(report: TokenReport, data: dict) -> None:
    attributes = _attributes(data)
    if not attributes:
        report.errors.append("GeckoTerminal: token not found")
        return
    report.symbol = attributes.get("symbol")
    report.name = attributes.get("name")
    report.price_usd = to_decimal(attributes.get("price_usd"))
    liquidity = to_decimal(attributes.get("total_reserve_in_usd"))
    report.liquidity_usd = liquidity.quantize(Decimal("0.01")) if liquidity is not None else None
    report.volume_24h = to_decimal((attributes.get("volume_usd") or {}).get("h24"))


HONEYPOT_FLAGS = {"yes": True, "no": False}


def apply_holders(report: TokenReport, data: dict) -> None:
    attributes = _attributes(data)
    report.gt_honeypot = HONEYPOT_FLAGS.get(str(attributes.get("is_honeypot")).lower())
    report.developer_address = attributes.get("developer_address")
    report.developer_holding_pct = to_decimal(attributes.get("developer_holding_percentage"))
    holders = attributes.get("holders") or {}
    distribution = holders.get("distribution_percentage") or {}
    report.holders_count = holders.get("count")
    report.top10_holders_pct = to_decimal(distribution.get("top_10"))
    if report.top10_holders_pct is None:
        report.errors.append("Holders: no data")
