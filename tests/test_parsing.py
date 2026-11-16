import asyncio
from decimal import Decimal

import aiohttp
import pytest

from rimex.clients.common import describe_error
from rimex.clients.dexscreener import apply as apply_dexscreener
from rimex.clients.rugcheck import apply as apply_rugcheck
from rimex.clients.solana_rpc import apply_mint_account
from rimex.domain.address import is_valid_address
from rimex.domain.models import TokenReport
from rimex.domain.risk import lp_risk_level, top10_risk_level
from rimex.presentation.formatting import format_money
from tests.conftest import BONK


def test_dexscreener_picks_most_liquid_pair(dexscreener_pairs):
    report = TokenReport(address=BONK)

    apply_dexscreener(report, dexscreener_pairs)

    assert report.symbol == "Bonk"
    assert report.price_usd == Decimal("0.000002357")
    assert report.liquidity_usd == Decimal("230519.95")
    assert report.volume_24h == Decimal("405716.67")


def test_dexscreener_price_is_decimal_not_float(dexscreener_pairs):
    report = TokenReport(address=BONK)

    apply_dexscreener(report, dexscreener_pairs)

    assert isinstance(report.price_usd, Decimal)


def test_dexscreener_empty_pairs_adds_error():
    report = TokenReport(address=BONK)

    apply_dexscreener(report, [])

    assert report.symbol is None
    assert report.errors == ["DexScreener: no pairs found"]


def test_dexscreener_tolerates_missing_fields():
    report = TokenReport(address=BONK)

    apply_dexscreener(report, [{"baseToken": {"symbol": "X"}, "liquidity": None}])

    assert report.symbol == "X"
    assert report.price_usd is None
    assert report.liquidity_usd is None


def test_mint_account_without_authorities_is_safe(mint_account):
    report = TokenReport(address=BONK)

    apply_mint_account(report, mint_account)

    assert report.authorities_loaded is True
    assert report.mint_authority is None
    assert report.freeze_authority is None


def test_mint_account_with_authorities(mint_account):
    info = mint_account["result"]["value"]["data"]["parsed"]["info"]
    info["mintAuthority"] = "MintOwner111"
    info["freezeAuthority"] = "FreezeOwner111"
    report = TokenReport(address=BONK)

    apply_mint_account(report, mint_account)

    assert report.mint_authority == "MintOwner111"
    assert report.freeze_authority == "FreezeOwner111"


@pytest.mark.parametrize(
    "response",
    [
        {"result": {"value": None}},
        {"result": {"value": {"data": ["base64data", "base64"]}}},
        {"result": {"value": {"data": {"parsed": {"type": "account", "info": {}}}}}},
    ],
    ids=["account-missing", "not-parsed", "not-a-mint"],
)
def test_non_mint_account_keeps_authorities_unknown(response):
    report = TokenReport(address=BONK)

    apply_mint_account(report, response)

    assert report.authorities_loaded is False
    assert report.errors == ["Solana RPC: address is not a token mint"]


def test_rugcheck_summary(rugcheck_summary):
    report = TokenReport(address=BONK)

    apply_rugcheck(report, rugcheck_summary)

    assert report.risk_score == 7
    assert report.lp_locked_pct == Decimal("19.428788418908034")
    assert report.risks == ["Mutable metadata"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (Decimal("100"), "safe"),
        (Decimal("90"), "safe"),
        (Decimal("89.99"), "warning"),
        (Decimal("50"), "warning"),
        (Decimal("49.99"), "danger"),
        (Decimal("0"), "danger"),
    ],
)
def test_lp_risk_level_boundaries(value, expected):
    assert lp_risk_level(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (Decimal("10"), "safe"),
        (Decimal("34.99"), "safe"),
        (Decimal("35"), "warning"),
        (Decimal("69.99"), "warning"),
        (Decimal("70"), "danger"),
    ],
)
def test_top10_risk_level_boundaries(value, expected):
    assert top10_risk_level(value) == expected


@pytest.mark.parametrize(
    ("address", "valid"),
    [
        (BONK, True),
        ("11111111111111111111111111111111", True),
        ("abc", False),
        ("", False),
        ("0" * 44, False),
        ("O" + BONK[1:], False),
        (BONK + "x" * 10, False),
        (" " + BONK, False),
    ],
)
def test_is_valid_address(address, valid):
    assert is_valid_address(address) is valid


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "—"),
        (Decimal("1234567.891"), "$1,234,567.89"),
        (Decimal("0.000002350"), "$0.00000235"),
    ],
)
def test_format_money(value, expected):
    assert format_money(value) == expected


def make_response_error(status: int) -> aiohttp.ClientResponseError:
    return aiohttp.ClientResponseError(request_info=None, history=(), status=status)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (asyncio.TimeoutError(), "no response in time (timeout)"),
        (make_response_error(400), "request rejected (HTTP 400)"),
        (make_response_error(503), "server error (HTTP 503)"),
        (aiohttp.ClientConnectionError(), "connection error (ClientConnectionError)"),
    ],
)
def test_describe_error(error, expected):
    assert describe_error(error) == expected
