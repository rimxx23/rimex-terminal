from urllib.parse import urlencode

from aiogram.types import InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

REFRESH_PREFIX = "refresh:"


def build_share_url(bot_username: str, address: str) -> str:
    deep_link = f"https://t.me/{bot_username}?startapp={address}"
    text = "Check this Solana token with Rimex X-Ray"
    return f"https://t.me/share/url?{urlencode({'url': deep_link, 'text': text})}"


def build_app_url(webapp_url: str, address: str) -> str:
    return f"{webapp_url.rstrip('/')}/?{urlencode({'address': address})}"


def build_start_keyboard(webapp_url: str | None) -> InlineKeyboardMarkup | None:
    if not webapp_url:
        return None
    builder = InlineKeyboardBuilder()
    builder.button(text="🔍 Open X-Ray", web_app=WebAppInfo(url=webapp_url))
    return builder.as_markup()


def build_open_app_keyboard(
    address: str,
    webapp_url: str,
    bot_username: str | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔍 Open in X-Ray", web_app=WebAppInfo(url=build_app_url(webapp_url, address)))
    if bot_username:
        builder.button(text="📤 Share", url=build_share_url(bot_username, address))
    builder.adjust(1)
    return builder.as_markup()


def build_keyboard(
    address: str,
    webapp_url: str | None = None,
    bot_username: str | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="DexScreener", url=f"https://dexscreener.com/solana/{address}")
    builder.button(text="RugCheck", url=f"https://rugcheck.xyz/tokens/{address}")
    builder.button(text="Solscan", url=f"https://solscan.io/token/{address}")
    layout = [3]
    if webapp_url:
        builder.button(text="🔍 Open in X-Ray", web_app=WebAppInfo(url=build_app_url(webapp_url, address)))
        layout.append(1)
    bottom_row = 1
    if bot_username:
        builder.button(text="📤 Share", url=build_share_url(bot_username, address))
        bottom_row = 2
    builder.button(text="🔄 Refresh", callback_data=f"{REFRESH_PREFIX}{address}")
    layout.append(bottom_row)
    builder.adjust(*layout)
    return builder.as_markup()
