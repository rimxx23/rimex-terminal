from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from rimex.clients.dexscreener import apply as apply_dexscreener
from rimex.clients.geckoterminal import apply_holders
from rimex.domain.known_tokens import KNOWN_TOKENS, find_known_token
from rimex.domain.models import TokenReport
from rimex.domain.risk import assess_honeypot, dev_holding_risk_level, pool_age_risk_level
from rimex.presentation.api.schemas import ScanResponse
from rimex.presentation.cli import format_report
from rimex.presentation.formatting import format_pool_age, human_age
from tests.conftest import BONK

USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


def test_known_tokens_are_valid_addresses():
    from rimex.domain.address import is_valid_address

    assert all(is_valid_address(address) for address in KNOWN_TOKENS)


def test_find_known_token():
    assert find_known_token(USDC).issuer == "Circle"
    assert find_known_token(BONK) is None


def test_known_issuer_powers_are_warning_not_danger():
    report = TokenReport(address=USDC, authorities_loaded=True, freeze_authority="Freeze1111", permanent_delegate="Delegate1111")

    assessment = assess_honeypot(report)

    assert assessment.level == "warning"
    assert assessment.reasons == ["regulated issuer (Circle) can freeze or move tokens"]


def test_known_token_still_danger_for_transfer_hook():
    report = TokenReport(address=USDC, authorities_loaded=True, freeze_authority="Freeze1111", transfer_hook_program="Hook1111")

    assessment = assess_honeypot(report)

    assert assessment.level == "danger"
    assert "transfer hook can block selling" in assessment.reasons


def test_unknown_token_with_same_powers_is_danger():
    report = TokenReport(address=BONK, authorities_loaded=True, freeze_authority="Freeze1111")

    assert assess_honeypot(report).level == "danger"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (Decimal("0"), "safe"),
        (Decimal("4.99"), "safe"),
        (Decimal("5"), "warning"),
        (Decimal("19.99"), "warning"),
        (Decimal("20"), "danger"),
    ],
)
def test_dev_holding_levels(value, expected):
    assert dev_holding_risk_level(value) == expected


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (timedelta(minutes=30), "danger"),
        (timedelta(hours=23, minutes=59), "danger"),
        (timedelta(days=1), "warning"),
        (timedelta(days=6, hours=23), "warning"),
        (timedelta(days=7), "safe"),
        (timedelta(days=700), "safe"),
    ],
)
def test_pool_age_levels(age, expected):
    assert pool_age_risk_level(NOW - age, NOW) == expected


def test_pool_age_unknown():
    assert pool_age_risk_level(None, NOW) is None


@pytest.mark.parametrize(
    ("age", "text"),
    [
        (timedelta(minutes=12), "12m"),
        (timedelta(hours=5), "5h"),
        (timedelta(hours=47), "47h"),
        (timedelta(days=3), "3d"),
        (timedelta(days=90), "3mo"),
        (timedelta(days=730), "2.0y"),
    ],
)
def test_human_age(age, text):
    assert human_age(NOW - age, NOW) == text


def test_format_pool_age_with_level():
    assert format_pool_age(NOW - timedelta(hours=3), NOW) == "🔴 3h"
    assert format_pool_age(None, NOW) == "—"


def test_dexscreener_parses_pool_creation_time():
    report = TokenReport(address=BONK)

    apply_dexscreener(report, [{"baseToken": {"symbol": "X"}, "pairCreatedAt": 1706675725000}])

    assert report.pool_created_at == datetime(2024, 1, 31, 4, 35, 25, tzinfo=UTC)


def test_dexscreener_without_creation_time():
    report = TokenReport(address=BONK)

    apply_dexscreener(report, [{"baseToken": {"symbol": "X"}}])

    assert report.pool_created_at is None


def test_geckoterminal_parses_developer_holding():
    report = TokenReport(address=BONK)

    apply_holders(report, {"data": {"attributes": {
        "developer_address": "Dev1111",
        "developer_holding_percentage": "12.5",
        "holders": {"count": 10, "distribution_percentage": {"top_10": "40"}},
    }}})

    assert report.developer_address == "Dev1111"
    assert report.developer_holding_pct == Decimal("12.5")


def test_api_response_has_new_fields():
    report = TokenReport(
        address=USDC,
        authorities_loaded=True,
        pool_created_at=NOW - timedelta(hours=2),
        developer_holding_pct=Decimal("25"),
    )

    response = ScanResponse.from_report(report, now=NOW)

    assert response.known_issuer == "Circle"
    assert response.pool_age_level == "danger"
    assert response.dev_level == "danger"


def test_cli_shows_known_token_and_new_rows():
    report = TokenReport(address=USDC, authorities_loaded=True, developer_holding_pct=Decimal("1"))

    cli = format_report(report)

    assert "✅ Known token: USDC by Circle" in cli
    assert "Developer:      🟢 1.0%" in cli
