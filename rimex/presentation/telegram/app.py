import logging

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import MenuButtonDefault, MenuButtonWebApp, WebAppInfo

from rimex import config
from rimex.clients.common import create_http_session
from rimex.presentation.telegram.handlers import create_router


def create_bot(token: str) -> Bot:
    return Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


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


async def run_polling() -> None:
    if not config.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")
    webapp_url = validate_webapp_url(config.WEBAPP_URL)

    logging.basicConfig(level=logging.INFO)
    bot = create_bot(config.BOT_TOKEN)
    await bot.delete_webhook()
    await setup_menu_button(bot, webapp_url)

    async with create_http_session() as http_session:
        dispatcher = create_dispatcher(http_session, webapp_url)
        await dispatcher.start_polling(bot)
