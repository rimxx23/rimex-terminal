from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from rimex.domain.address import short_address
from rimex.domain.models import TokenReport
from rimex.presentation.telegram import handlers
from rimex.presentation.telegram.cards import format_card, format_open_app_message
from rimex.presentation.telegram.keyboards import (
    REFRESH_PREFIX,
    build_keyboard,
    build_open_app_keyboard,
)
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


class FakeBot:
    async def me(self):
        return SimpleNamespace(username="rimexscanner_bot")


class FakeMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.bot = FakeBot()
        self.answers = []

    async def answer(self, text, reply_markup=None):
        self.answers.append((text, reply_markup))


WEBAPP_URL = "https://rimex-terminal.onrender.com"


def test_open_app_message_shows_short_address():
    text = format_open_app_message(BONK)

    assert "<code>DezX…B263</code>" in text
    assert "Open in X-Ray" in text


def test_open_app_keyboard_opens_mini_app_with_token():
    keyboard = build_open_app_keyboard(BONK, WEBAPP_URL, "rimexscanner_bot")

    open_button, share_button = [row[0] for row in keyboard.inline_keyboard]

    assert open_button.web_app.url == f"{WEBAPP_URL}/?address={BONK}"
    assert share_button.text == "📤 Share"


async def test_address_message_links_to_mini_app_without_scanning(monkeypatch):
    async def must_not_scan(*args, **kwargs):
        raise AssertionError("bot must not scan on the server when Mini App is configured")

    monkeypatch.setattr(handlers, "run_scan", must_not_scan)
    message = FakeMessage(BONK)

    await handlers.handle_address(message, http_session=None, webapp_url=WEBAPP_URL)

    text, keyboard = message.answers[0]
    assert short_address(BONK) in text
    assert keyboard.inline_keyboard[0][0].web_app.url == f"{WEBAPP_URL}/?address={BONK}"


async def test_address_message_scans_when_no_mini_app(monkeypatch):
    scanned = []

    async def fake_scan(address, http_session):
        scanned.append(address)
        return make_report()

    class EditableStatus:
        async def edit_text(self, text, reply_markup=None):
            self.text = text

    status = EditableStatus()

    class ScanningMessage(FakeMessage):
        async def answer(self, text, reply_markup=None):
            return status

    monkeypatch.setattr(handlers, "run_scan", fake_scan)

    await handlers.handle_address(ScanningMessage(BONK), http_session=None, webapp_url=None)

    assert scanned == [BONK]
    assert "Bonk" in status.text


async def test_invalid_address_gets_hint():
    message = FakeMessage("hello")

    await handlers.handle_address(message, http_session=None, webapp_url=WEBAPP_URL)

    assert "doesn't look like a Solana token address" in message.answers[0][0]
