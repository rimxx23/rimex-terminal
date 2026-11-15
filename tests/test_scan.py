import asyncio
from decimal import Decimal

import pytest

import scanner
from scanner import scan_solana_token
from tests.conftest import BONK


@pytest.fixture
def fake_sources(monkeypatch, dexscreener_pairs, mint_account, rugcheck_summary):
    calls = []
    results = {
        "dex": dexscreener_pairs,
        "rpc": mint_account,
        "rug": rugcheck_summary,
    }

    def make_fetcher(name):
        async def fetch(session, address):
            calls.append(name)
            result = results[name]
            if isinstance(result, BaseException):
                raise result
            return result

        return fetch

    monkeypatch.setattr(scanner, "fetch_dexscreener", make_fetcher("dex"))
    monkeypatch.setattr(scanner, "fetch_mint_account", make_fetcher("rpc"))
    monkeypatch.setattr(scanner, "fetch_rugcheck", make_fetcher("rug"))
    return results, calls


async def test_full_scan_combines_all_sources(fake_sources):
    report = await scan_solana_token(BONK, session=object())

    assert report.symbol == "Bonk"
    assert report.authorities_loaded is True
    assert report.lp_locked_pct == Decimal("19.428788418908034")
    assert report.errors == []


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
        return []

    monkeypatch.setattr(scanner, "fetch_dexscreener", slow_list)
    monkeypatch.setattr(scanner, "fetch_mint_account", slow)
    monkeypatch.setattr(scanner, "fetch_rugcheck", slow)

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


async def test_rugcheck_response_is_cached(rugcheck_summary):
    session = FakeSession(rugcheck_summary)

    first = await scanner.fetch_rugcheck(session, BONK)
    second = await scanner.fetch_rugcheck(session, BONK)

    assert first == second == rugcheck_summary
    assert session.requests == 1


async def test_rugcheck_cache_expires(monkeypatch, rugcheck_summary):
    session = FakeSession(rugcheck_summary)
    now = [1000.0]
    monkeypatch.setattr(scanner.time, "monotonic", lambda: now[0])

    await scanner.fetch_rugcheck(session, BONK)
    now[0] += scanner.RUGCHECK_CACHE_TTL + 1
    await scanner.fetch_rugcheck(session, BONK)

    assert session.requests == 2
