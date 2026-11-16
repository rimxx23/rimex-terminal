import asyncio
import time

import aiohttp

from rimex.clients import dexscreener, geckoterminal, rugcheck, solana_rpc
from rimex.clients.common import create_http_session, describe_error
from rimex.domain.address import is_valid_address
from rimex.domain.models import TokenReport

MARKET_APPLIERS = {
    dexscreener.SOURCE: dexscreener.apply,
    geckoterminal.SOURCE: geckoterminal.apply_token,
}


class MarketDataUnavailable(Exception):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


async def fetch_market(session: aiohttp.ClientSession, address: str) -> tuple[str, list | dict]:
    reasons = []
    try:
        pairs = await dexscreener.fetch(session, address)
        if pairs:
            return dexscreener.SOURCE, pairs
        reasons.append("DexScreener: no pairs found")
    except Exception as error:
        reasons.append(f"DexScreener: {describe_error(error)}")

    try:
        return geckoterminal.SOURCE, await geckoterminal.fetch_token(session, address)
    except aiohttp.ClientResponseError as error:
        if error.status == 404:
            reasons.append("GeckoTerminal: token not found")
        else:
            reasons.append(f"GeckoTerminal: {describe_error(error)}")
    except Exception as error:
        reasons.append(f"GeckoTerminal: {describe_error(error)}")
    raise MarketDataUnavailable(reasons)


def apply_market(report: TokenReport, result: tuple[str, list | dict]) -> None:
    source, data = result
    report.market_source = source
    MARKET_APPLIERS[source](report, data)


async def fetch_all(session: aiohttp.ClientSession, address: str) -> list:
    return await asyncio.gather(
        fetch_market(session, address),
        solana_rpc.fetch_mint_account(session, address),
        rugcheck.fetch(session, address),
        geckoterminal.fetch_info(session, address),
        return_exceptions=True,
    )


async def scan_solana_token(
    address: str, session: aiohttp.ClientSession | None = None
) -> TokenReport:
    report = TokenReport(address=address)
    if not is_valid_address(address):
        report.errors.append("Invalid Solana address")
        return report

    started = time.perf_counter()
    if session is None:
        async with create_http_session() as own_session:
            results = await fetch_all(own_session, address)
    else:
        results = await fetch_all(session, address)
    market_result, rpc_result, rug_result, holders_result = results
    report.elapsed = time.perf_counter() - started

    sources = [
        ("Market data", market_result, apply_market),
        ("Solana RPC", rpc_result, solana_rpc.apply_mint_account),
        ("RugCheck", rug_result, rugcheck.apply),
        ("Holders", holders_result, geckoterminal.apply_holders),
    ]
    for source_name, result, apply in sources:
        if isinstance(result, MarketDataUnavailable):
            report.errors.extend(result.reasons)
        elif isinstance(result, BaseException):
            report.errors.append(f"{source_name}: {describe_error(result)}")
        else:
            apply(report, result)

    return report
