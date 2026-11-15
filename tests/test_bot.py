from decimal import Decimal

from bot import REFRESH_PREFIX, build_keyboard, format_card
from scanner import TokenReport
from tests.conftest import BONK


def make_report(**overrides) -> TokenReport:
    fields = {
        "address": BONK,
        "symbol": "Bonk",
        "name": "Bonk",
        "price_usd": Decimal("0.000002357"),
        "authorities_loaded": True,
        "lp_locked_pct": Decimal("95"),
        "elapsed": 0.42,
    }
    fields.update(overrides)
    return TokenReport(**fields)


def test_card_escapes_html_in_token_name():
    report = make_report(symbol="<b>SCAM</b>", name='<a href="https://phishing.example">Claim</a>')

    card = format_card(report)

    assert "<a href" not in card
    assert "&lt;b&gt;SCAM&lt;/b&gt;" in card
    assert "&lt;a href=&quot;https://phishing.example&quot;&gt;" in card


def test_card_escapes_html_in_errors_and_risks():
    report = make_report(risks=["<script>"], errors=["<i>boom</i>"])

    card = format_card(report)

    assert "<script>" not in card
    assert "<i>boom</i>" not in card


def test_card_marks_enabled_authority_as_danger():
    report = make_report(mint_authority="MintOwner1111111111")

    card = format_card(report)

    assert "🔴 <b>enabled</b>" in card


def test_card_shows_unknown_when_rpc_failed():
    report = make_report(authorities_loaded=False)

    card = format_card(report)

    assert "⚪ unknown" in card
    assert "🟢 disabled" not in card


def test_refresh_callback_fits_telegram_limit():
    longest_address = "1" * 44

    keyboard = build_keyboard(longest_address)
    refresh_button = keyboard.inline_keyboard[-1][0]

    assert refresh_button.callback_data == f"{REFRESH_PREFIX}{longest_address}"
    assert len(refresh_button.callback_data.encode()) <= 64
