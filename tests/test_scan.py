import asyncio
from decimal import Decimal

import aiohttp
import pytest

from rimex.clients import dexscreener, geckoterminal, rugcheck, solana_rpc
from rimex.services.scanner import scan_solana_token
from tests.conftest import BONK


GECKOTERMINAL_TOKEN = {
    "data": {
        "attributes": {
            "symbol": "JUP",
            "name": "Jupiter",
            "price_usd": "0.2636258854",
            "total_reserve_in_usd": "3056699.535273792832",
            "volume_usd": {"h24": "7254175.19"},
        }
    }
}


GECKOTERMINAL_INFO = {
    "data": {
        "attributes": {
            "holders": {
                "count": 828512,
                "distribution_percentage": {"top_10": "65.1765", "11_20": "6.4", "21_40": "5.6", "rest": "22.7"},
            }
        }
    }
}


def response_error(status: int) -> aiohttp.ClientResponseError:
    return aiohttp.ClientResponseError(request_info=None, history=(), status=status)


@pytest.fixture(autouse=True)
def no_real_geckoterminal(monkeypatch):
    async def blocked(session, address):
        raise AssertionError("GeckoTerminal must be mocked in tests")

    monkeypatch.setattr(geckoterminal, "fetch_token", blocked)
    monkeypatch.setattr(geckoterminal, "fetch_info", blocked)


@pytest.fixture
def fake_sources(monkeypatch, dexscreener_pairs, mint_account, rugcheck_summary):
    calls = []
    results = {
        "dex": dexscreener_pairs,
        "gecko": GECKOTERMINAL_TOKEN,
        "rpc": mint_account,
        "rug": rugcheck_summary,
        "holders": GECKOTERMINAL_INFO,
    }

    def make_fetcher(name):
        async def fetch(session, address):
            calls.append(name)
            result = results[name]
            if isinstance(result, BaseException):
                raise result
            return result

        return fetch

    monkeypatch.setattr(dexscreener, "fetch", make_fetcher("dex"))
    monkeypatch.setattr(geckoterminal, "fetch_token", make_fetcher("gecko"))
    monkeypatch.setattr(solana_rpc, "fetch_mint_account", make_fetcher("rpc"))
    monkeypatch.setattr(rugcheck, "fetch", make_fetcher("rug"))
    monkeypatch.setattr(geckoterminal, "fetch_info", make_fetcher("holders"))
    return results, calls


async def test_full_scan_combines_all_sources(fake_sources):
    report = await scan_solana_token(BONK, session=object())

    assert report.symbol == "Bonk"
    assert report.market_source == "DexScreener"
    assert report.authorities_loaded is True
    assert report.lp_locked_pct == Decimal("19.428788418908034")
    assert report.errors == []


async def test_holders_concentration(fake_sources):
    report = await scan_solana_token(BONK, session=object())

    assert report.holders_count == 828512
    assert report.top10_holders_pct == Decimal("65.1765")


async def test_holders_failure_keeps_other_data(fake_sources):
    results, _ = fake_sources
    results["holders"] = response_error(429)

    report = await scan_solana_token(BONK, session=object())

    assert report.top10_holders_pct is None
    assert report.symbol == "Bonk"
    assert report.errors == ["Holders: request rejected (HTTP 429)"]


async def test_holders_missing_in_response(fake_sources):
    results, _ = fake_sources
    results["holders"] = {"data": {"attributes": {}}}

    report = await scan_solana_token(BONK, session=object())

    assert report.top10_holders_pct is None
    assert report.errors == ["Holders: no data"]


async def test_geckoterminal_not_called_when_dexscreener_works(fake_sources):
    _, calls = fake_sources

    await scan_solana_token(BONK, session=object())

    assert "gecko" not in calls


async def test_falls_back_to_geckoterminal_when_dexscreener_rate_limited(fake_sources):
    results, _ = fake_sources
    results["dex"] = response_error(429)

    report = await scan_solana_token(BONK, session=object())

    assert report.market_source == "GeckoTerminal"
    assert report.symbol == "JUP"
    assert report.price_usd == Decimal("0.2636258854")
    assert report.liquidity_usd == Decimal("3056699.54")
    assert report.errors == []


async def test_falls_back_to_geckoterminal_when_dexscreener_has_no_pairs(fake_sources):
    results, _ = fake_sources
    results["dex"] = []

    report = await scan_solana_token(BONK, session=object())

    assert report.market_source == "GeckoTerminal"


async def test_both_market_sources_failing_keeps_security_data(fake_sources):
    results, _ = fake_sources
    results["dex"] = response_error(429)
    results["gecko"] = response_error(404)

    report = await scan_solana_token(BONK, session=object())

    assert report.market_source is None
    assert report.price_usd is None
    assert report.authorities_loaded is True
    assert report.errors == [
        "DexScreener: request rejected (HTTP 429)",
        "GeckoTerminal: token not found",
    ]


async def test_invalid_address_makes_no_requests(fake_sources):
    _, calls = fake_sources

    report = await scan_solana_token("not-an-address", session=object())

    assert calls == []
    assert report.errors == ["Invalid Solana address"]


async def test_one_failed_source_does_not_break_scan(fake_sources):
    results, _ = fake_sources
    results["rug"] = asyncio.TimeoutError()

    report = await scan_solana_token(BONK, session=object())

    assert report.symbol == "Bonk"
    assert report.authorities_loaded is True
    assert report.lp_locked_pct is None
    assert report.errors == ["RugCheck: no response in time (timeout)"]


async def test_failed_rpc_never_reports_token_as_safe(fake_sources):
    results, _ = fake_sources
    results["rpc"] = ConnectionError()

    report = await scan_solana_token(BONK, session=object())

    assert report.authorities_loaded is False
    assert report.mint_authority is None
    assert any(error.startswith("Solana RPC:") for error in report.errors)


async def test_sources_run_in_parallel(monkeypatch):
    async def slow(session, address):
        await asyncio.sleep(0.2)
        return {}

    async def slow_list(session, address):
        await asyncio.sleep(0.2)
        return [{"baseToken": {"symbol": "X"}}]

    monkeypatch.setattr(dexscreener, "fetch", slow_list)
    monkeypatch.setattr(solana_rpc, "fetch_mint_account", slow)
    monkeypatch.setattr(rugcheck, "fetch", slow)
    monkeypatch.setattr(geckoterminal, "fetch_info", slow)

    report = await scan_solana_token(BONK, session=object())

    assert report.elapsed < 0.35


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def raise_for_status(self):
        pass

    async def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.requests = 0

    def get(self, url, **kwargs):
        self.requests += 1
        return FakeResponse(self.payload)


class FailingResponse(FakeResponse):
    def __init__(self, status):
        super().__init__(None)
        self.status = status

    def raise_for_status(self):
        raise response_error(self.status)


class FakeRpcSession:
    def __init__(self, responses):
        self.responses = responses
        self.urls = []

    def post(self, url, **kwargs):
        self.urls.append(url)
        return self.responses[len(self.urls) - 1]


async def test_rpc_falls_back_to_next_node(monkeypatch, mint_account):
    monkeypatch.delenv("SOLANA_RPC_URL", raising=False)
    session = FakeRpcSession([FailingResponse(403), FakeResponse(mint_account)])

    data = await solana_rpc.fetch_mint_account(session, BONK)

    assert data == mint_account
    assert session.urls == [solana_rpc.DEFAULT_URL, *solana_rpc.FALLBACK_URLS]


async def test_rpc_error_body_triggers_fallback(monkeypatch, mint_account):
    monkeypatch.delenv("SOLANA_RPC_URL", raising=False)
    rate_limited = FakeResponse({"jsonrpc": "2.0", "error": {"code": 429, "message": "Too many requests"}})
    session = FakeRpcSession([rate_limited, FakeResponse(mint_account)])

    assert await solana_rpc.fetch_mint_account(session, BONK) == mint_account


async def test_rpc_raises_when_all_nodes_fail(monkeypatch):
    monkeypatch.delenv("SOLANA_RPC_URL", raising=False)
    session = FakeRpcSession([FailingResponse(403), FailingResponse(429)])

    with pytest.raises(aiohttp.ClientResponseError):
        await solana_rpc.fetch_mint_account(session, BONK)


async def test_custom_rpc_url_is_tried_first(monkeypatch, mint_account):
    monkeypatch.setenv("SOLANA_RPC_URL", "https://mainnet.helius-rpc.com/?api-key=test")
    session = FakeRpcSession([FakeResponse(mint_account)])

    await solana_rpc.fetch_mint_account(session, BONK)

    assert session.urls == ["https://mainnet.helius-rpc.com/?api-key=test"]


async def test_rugcheck_response_is_cached(rugcheck_summary):
    session = FakeSession(rugcheck_summary)

    first = await rugcheck.fetch(session, BONK)
    second = await rugcheck.fetch(session, BONK)

    assert first == second == rugcheck_summary
    assert session.requests == 1


async def test_rugcheck_cache_expires(monkeypatch, rugcheck_summary):
    session = FakeSession(rugcheck_summary)
    now = [1000.0]
    monkeypatch.setattr(rugcheck.time, "monotonic", lambda: now[0])

    await rugcheck.fetch(session, BONK)
    now[0] += rugcheck.CACHE_TTL + 1
    await rugcheck.fetch(session, BONK)

    assert session.requests == 2
