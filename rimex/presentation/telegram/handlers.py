import asyncio

import aiohttp
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from rimex.domain.address import is_valid_address
from rimex.domain.models import TokenReport
from rimex.presentation.ratelimit import SlidingWindowLimiter
from rimex.presentation.telegram.cards import START_MESSAGE, format_card, format_open_app_message
from rimex.presentation.telegram.keyboards import (
    REFRESH_PREFIX,
    build_keyboard,
    build_open_app_keyboard,
    build_start_keyboard,
)
from rimex.presentation.telegram.middlewares import RateLimitMiddleware
from rimex.services.scanner import scan_solana_token

USER_RATE_LIMIT = 5
USER_RATE_PERIOD = 60
MAX_CONCURRENT_SCANS = 10

scan_slots = asyncio.Semaphore(MAX_CONCURRENT_SCANS)


async def run_scan(address: str, http_session: aiohttp.ClientSession) -> TokenReport:
    async with scan_slots:
        return await scan_solana_token(address, http_session)


async def reply_with_app_link(message: Message, address: str, webapp_url: str, edit: bool = False) -> None:
    me = await message.bot.me()
    text = format_open_app_message(address)
    keyboard = build_open_app_keyboard(address, webapp_url, me.username)
    if edit:
        await message.edit_text(text, reply_markup=keyboard)
    else:
        await message.answer(text, reply_markup=keyboard)


async def card_keyboard(bot: Bot, address: str, webapp_url: str | None) -> InlineKeyboardMarkup:
    me = await bot.me()
    return build_keyboard(address, webapp_url, me.username)


async def handle_start(message: Message, webapp_url: str | None) -> None:
    await message.answer(START_MESSAGE, reply_markup=build_start_keyboard(webapp_url))


async def handle_address(
    message: Message,
    http_session: aiohttp.ClientSession,
    webapp_url: str | None,
) -> None:
    address = message.text.strip()
    if not is_valid_address(address):
        await message.answer("This doesn't look like a Solana token address. Send a contract address.")
        return
    if webapp_url:
        await reply_with_app_link(message, address, webapp_url)
        return
    status = await message.answer("🔍 Scanning…")
    report = await run_scan(address, http_session)
    keyboard = await card_keyboard(message.bot, address, webapp_url)
    await status.edit_text(format_card(report), reply_markup=keyboard)


async def handle_refresh(
    callback: CallbackQuery,
    http_session: aiohttp.ClientSession,
    webapp_url: str | None,
) -> None:
    address = callback.data.removeprefix(REFRESH_PREFIX)
    if not is_valid_address(address):
        await callback.answer("Invalid address", show_alert=True)
        return
    if webapp_url:
        await callback.answer()
        await reply_with_app_link(callback.message, address, webapp_url, edit=True)
        return
    await callback.answer("Refreshing…")
    report = await run_scan(address, http_session)
    try:
        keyboard = await card_keyboard(callback.bot, address, webapp_url)
        await callback.message.edit_text(format_card(report), reply_markup=keyboard)
    except TelegramBadRequest as error:
        if "message is not modified" not in str(error):
            raise


def create_router() -> Router:
    router = Router()
    router.message.register(handle_start, CommandStart())
    router.message.register(handle_address, F.text)
    router.callback_query.register(handle_refresh, F.data.startswith(REFRESH_PREFIX))
    rate_limit = RateLimitMiddleware(SlidingWindowLimiter(USER_RATE_LIMIT, USER_RATE_PERIOD))
    router.message.middleware(rate_limit)
    router.callback_query.middleware(rate_limit)
    return router
