import asyncio
import html
import logging
import os

import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    MenuButtonDefault,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

from middlewares import RateLimitMiddleware
from ratelimit import SlidingWindowLimiter
from scanner import (
    TokenReport,
    create_http_session,
    format_lp,
    format_money,
    is_valid_address,
    scan_solana_token,
)

REFRESH_PREFIX = "refresh:"
USER_RATE_LIMIT = 5
USER_RATE_PERIOD = 60
MAX_CONCURRENT_SCANS = 10

scan_slots = asyncio.Semaphore(MAX_CONCURRENT_SCANS)


async def run_scan(address: str, http_session: aiohttp.ClientSession) -> TokenReport:
    async with scan_slots:
        return await scan_solana_token(address, http_session)


def format_authority_html(value: str | None, loaded: bool) -> str:
    if not loaded:
        return "⚪ unknown"
    if value is None:
        return "🟢 disabled"
    return f"🔴 <b>enabled</b> (<code>{value[:4]}…{value[-4:]}</code>)"


def format_card(report: TokenReport) -> str:
    symbol = html.escape(report.symbol or "?")
    name = html.escape(report.name or "?")
    risk = report.risk_score if report.risk_score is not None else "—"
    lines = [
        f"<b>{symbol}</b> · {name}",
        f"<code>{report.address}</code>",
        "",
        f"💵 Price: <b>{format_money(report.price_usd)}</b>",
        f"💧 Liquidity: {format_money(report.liquidity_usd)}",
        f"📊 Volume 24h: {format_money(report.volume_24h)}",
        "",
        "<b>X-Ray security</b>",
        f"Mint Authority: {format_authority_html(report.mint_authority, report.authorities_loaded)}",
        f"Freeze Authority: {format_authority_html(report.freeze_authority, report.authorities_loaded)}",
        f"LP locked: {format_lp(report.lp_locked_pct)}",
        f"RugCheck risk: {risk} (lower is safer)",
    ]
    if report.risks:
        lines.append(f"Risks: {html.escape(', '.join(report.risks))}")
    if report.errors:
        lines.append("")
        lines.extend(f"⚠️ {html.escape(error)}" for error in report.errors)
    lines.append("")
    source = f" · market data: {html.escape(report.market_source)}" if report.market_source else ""
    lines.append(f"<i>Scanned in {report.elapsed:.2f}s{source}</i>")
    return "\n".join(lines)


def build_keyboard(address: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="DexScreener", url=f"https://dexscreener.com/solana/{address}")
    builder.button(text="RugCheck", url=f"https://rugcheck.xyz/tokens/{address}")
    builder.button(text="Solscan", url=f"https://solscan.io/token/{address}")
    builder.button(text="🔄 Refresh", callback_data=f"{REFRESH_PREFIX}{address}")
    builder.adjust(3, 1)
    return builder.as_markup()


async def handle_start(message: Message, webapp_url: str | None) -> None:
    keyboard = None
    if webapp_url:
        builder = InlineKeyboardBuilder()
        builder.button(text="🔍 Open X-Ray", web_app=WebAppInfo(url=webapp_url))
        keyboard = builder.as_markup()
    await message.answer(
        "<b>Rimex X-Ray</b>\n\n"
        "Send me a Solana token contract address and I will check it in under a second:\n"
        "price, liquidity, Mint/Freeze authority and LP lock.",
        reply_markup=keyboard,
    )


async def handle_address(message: Message, http_session: aiohttp.ClientSession) -> None:
    address = message.text.strip()
    if not is_valid_address(address):
        await message.answer("This doesn't look like a Solana token address. Send a contract address.")
        return
    status = await message.answer("🔍 Scanning…")
    report = await run_scan(address, http_session)
    await status.edit_text(format_card(report), reply_markup=build_keyboard(address))


async def handle_refresh(callback: CallbackQuery, http_session: aiohttp.ClientSession) -> None:
    address = callback.data.removeprefix(REFRESH_PREFIX)
    if not is_valid_address(address):
        await callback.answer("Invalid address", show_alert=True)
        return
    await callback.answer("Refreshing…")
    report = await run_scan(address, http_session)
    try:
        await callback.message.edit_text(format_card(report), reply_markup=build_keyboard(address))
    except TelegramBadRequest as error:
        if "message is not modified" not in str(error):
            raise


def create_bot(token: str) -> Bot:
    return Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def create_router() -> Router:
    router = Router()
    router.message.register(handle_start, CommandStart())
    router.message.register(handle_address, F.text)
    router.callback_query.register(handle_refresh, F.data.startswith(REFRESH_PREFIX))
    rate_limit = RateLimitMiddleware(SlidingWindowLimiter(USER_RATE_LIMIT, USER_RATE_PERIOD))
    router.message.middleware(rate_limit)
    router.callback_query.middleware(rate_limit)
    return router


def create_dispatcher(http_session: aiohttp.ClientSession, webapp_url: str | None) -> Dispatcher:
    dispatcher = Dispatcher(http_session=http_session, webapp_url=webapp_url)
    dispatcher.include_router(create_router())
    return dispatcher


def validate_webapp_url(webapp_url: str | None) -> str | None:
    if webapp_url and not webapp_url.startswith("https://"):
        raise RuntimeError("WEBAPP_URL must start with https:// (Telegram requirement).")
    return webapp_url or None


async def setup_menu_button(bot: Bot, webapp_url: str | None) -> None:
    if webapp_url:
        menu_button = MenuButtonWebApp(text="X-Ray", web_app=WebAppInfo(url=webapp_url))
    else:
        menu_button = MenuButtonDefault()
    await bot.set_chat_menu_button(menu_button=menu_button)


async def main() -> None:
    load_dotenv()
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")
    webapp_url = validate_webapp_url(os.getenv("WEBAPP_URL"))

    logging.basicConfig(level=logging.INFO)
    bot = create_bot(token)
    await bot.delete_webhook()
    await setup_menu_button(bot, webapp_url)

    async with create_http_session() as http_session:
        dispatcher = create_dispatcher(http_session, webapp_url)
        await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
