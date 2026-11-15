import asyncio
import re
import ssl
import sys
import time
from dataclasses import dataclass, field
from decimal import Decimal

import aiohttp
import certifi

DEXSCREENER_URL = "https://api.dexscreener.com/tokens/v1/solana/{address}"
RUGCHECK_URL = "https://api.rugcheck.xyz/v1/tokens/{address}/report/summary"
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=3)
RUGCHECK_TIMEOUT = aiohttp.ClientTimeout(total=1.5)
RUGCHECK_CACHE_TTL = 300
SOLANA_ADDRESS_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

_rugcheck_cache: dict[str, tuple[float, dict]] = {}


@dataclass
class TokenReport:
    address: str
    symbol: str | None = None
    name: str | None = None
    price_usd: Decimal | None = None
    liquidity_usd: Decimal | None = None
    volume_24h: Decimal | None = None
    authorities_loaded: bool = False
    mint_authority: str | None = None
    freeze_authority: str | None = None
    lp_locked_pct: Decimal | None = None
    risk_score: int | None = None
    risks: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    elapsed: float = 0.0


def is_valid_address(address: str) -> bool:
    return bool(SOLANA_ADDRESS_RE.match(address))


def to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


async def fetch_dexscreener(session: aiohttp.ClientSession, address: str) -> list:
    async with session.get(DEXSCREENER_URL.format(address=address)) as response:
        response.raise_for_status()
        return await response.json()


async def fetch_rugcheck(session: aiohttp.ClientSession, address: str) -> dict:
    cached = _rugcheck_cache.get(address)
    if cached and time.monotonic() - cached[0] < RUGCHECK_CACHE_TTL:
        return cached[1]
    url = RUGCHECK_URL.format(address=address)
    async with session.get(url, timeout=RUGCHECK_TIMEOUT) as response:
        response.raise_for_status()
        data = await response.json()
    _rugcheck_cache[address] = (time.monotonic(), data)
    return data


async def fetch_mint_account(session: aiohttp.ClientSession, address: str) -> dict:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getAccountInfo",
        "params": [address, {"encoding": "jsonParsed"}],
    }
    async with session.post(SOLANA_RPC_URL, json=payload) as response:
        response.raise_for_status()
        return await response.json()


def apply_dexscreener(report: TokenReport, pairs: list) -> None:
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


def apply_mint_account(report: TokenReport, data: dict) -> None:
    account = (data.get("result") or {}).get("value") or {}
    account_data = account.get("data")
    parsed = account_data.get("parsed") if isinstance(account_data, dict) else None
    if not parsed or parsed.get("type") != "mint":
        report.errors.append("Solana RPC: address is not a token mint")
        return
    info = parsed["info"]
    report.authorities_loaded = True
    report.mint_authority = info.get("mintAuthority")
    report.freeze_authority = info.get("freezeAuthority")


def apply_rugcheck(report: TokenReport, data: dict) -> None:
    report.risk_score = data.get("score_normalised")
    report.lp_locked_pct = to_decimal(data.get("lpLockedPct"))
    report.risks = [risk["name"] for risk in data.get("risks") or []]


def describe_error(error: BaseException) -> str:
    if isinstance(error, asyncio.TimeoutError):
        return "no response in time (timeout)"
    if isinstance(error, aiohttp.ClientResponseError):
        if 400 <= error.status < 500:
            return f"request rejected (HTTP {error.status})"
        return f"server error (HTTP {error.status})"
    return f"connection error ({type(error).__name__})"


def create_http_session() -> aiohttp.ClientSession:
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    return aiohttp.ClientSession(connector=connector, timeout=REQUEST_TIMEOUT)


async def fetch_all(session: aiohttp.ClientSession, address: str) -> list:
    return await asyncio.gather(
        fetch_dexscreener(session, address),
        fetch_mint_account(session, address),
        fetch_rugcheck(session, address),
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
    dex_result, rpc_result, rug_result = results
    report.elapsed = time.perf_counter() - started

    sources = [
        ("DexScreener", dex_result, apply_dexscreener),
        ("Solana RPC", rpc_result, apply_mint_account),
        ("RugCheck", rug_result, apply_rugcheck),
    ]
    for source_name, result, apply in sources:
        if isinstance(result, BaseException):
            report.errors.append(f"{source_name}: {describe_error(result)}")
        else:
            apply(report, result)

    return report


def format_money(value: Decimal | None) -> str:
    if value is None:
        return "—"
    if value >= 1:
        return f"${value:,.2f}"
    return f"${value:.10f}".rstrip("0")


def format_authority(value: str | None, loaded: bool) -> str:
    if not loaded:
        return "⚪ unknown"
    if value is None:
        return "🟢 disabled"
    return f"🔴 enabled ({value[:4]}…{value[-4:]})"


LP_SAFE_PCT = Decimal("90")
LP_WARNING_PCT = Decimal("50")
LEVEL_MARKS = {"safe": "🟢", "warning": "🟡", "danger": "🔴"}


def lp_risk_level(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value >= LP_SAFE_PCT:
        return "safe"
    if value >= LP_WARNING_PCT:
        return "warning"
    return "danger"


def format_lp(value: Decimal | None) -> str:
    level = lp_risk_level(value)
    if level is None:
        return "—"
    return f"{LEVEL_MARKS[level]} {value:.1f}%"


def format_report(report: TokenReport) -> str:
    risk = report.risk_score if report.risk_score is not None else "—"
    lines = [
        f"Token:          {report.symbol or '?'} ({report.name or '?'})",
        f"Address:        {report.address}",
        f"Price:          {format_money(report.price_usd)}",
        f"Liquidity:      {format_money(report.liquidity_usd)}",
        f"Volume 24h:     {format_money(report.volume_24h)}",
        f"Mint Authority: {format_authority(report.mint_authority, report.authorities_loaded)}",
        f"Freeze Auth.:   {format_authority(report.freeze_authority, report.authorities_loaded)}",
        f"LP locked:      {format_lp(report.lp_locked_pct)}",
        f"RugCheck risk:  {risk} (lower is safer)",
    ]
    if report.risks:
        lines.append(f"Risks:          {', '.join(report.risks)}")
    for error in report.errors:
        lines.append(f"⚠️  {error}")
    lines.append(f"Scan time:      {report.elapsed:.2f}s")
    return "\n".join(lines)


async def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scanner.py <token address>")
        sys.exit(1)
    report = await scan_solana_token(sys.argv[1])
    print(format_report(report))


if __name__ == "__main__":
    asyncio.run(main())
