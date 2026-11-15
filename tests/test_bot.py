from decimal import Decimal
from urllib.parse import parse_qs, urlparse

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


def test_keyboard_has_open_in_x_ray_button_with_address():
    keyboard = build_keyboard(BONK, webapp_url="https://rimex-terminal.onrender.com", bot_username="rimexscanner_bot")

    buttons = [button for row in keyboard.inline_keyboard for button in row]
    open_button = next(button for button in buttons if button.web_app)

    assert open_button.web_app.url == f"https://rimex-terminal.onrender.com/?address={BONK}"


def test_share_link_opens_mini_app_with_token():
    keyboard = build_keyboard(BONK, webapp_url="https://rimex-terminal.onrender.com", bot_username="rimexscanner_bot")

    share = next(button for row in keyboard.inline_keyboard for button in row if button.text == "📤 Share")
    query = parse_qs(urlparse(share.url).query)

    assert share.url.startswith("https://t.me/share/url?")
    assert query["url"] == [f"https://t.me/rimexscanner_bot?startapp={BONK}"]


def test_keyboard_without_webapp_has_no_mini_app_buttons():
    keyboard = build_keyboard(BONK)

    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert not any(button.web_app for button in buttons)
    assert [button.text for button in buttons][-1] == "🔄 Refresh"


def test_card_shows_top10_holders():
    report = make_report(top10_holders_pct=Decimal("82.5"), holders_count=1234)

    card = format_card(report)

    assert "Top 10 holders: 🔴 82.5%" in card
    assert "Holders: 1,234" in card
