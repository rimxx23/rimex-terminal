import time
from typing import Annotated

from aiogram.utils.web_app import safe_parse_webapp_init_data
from fastapi import Header, HTTPException

from rimex import config

INIT_DATA_MAX_AGE = 24 * 60 * 60


def get_telegram_user_id(
    x_telegram_init_data: Annotated[str | None, Header()] = None,
) -> int:
    if not x_telegram_init_data:
        raise HTTPException(status_code=401, detail="Open this app from Telegram")
    try:
        init_data = safe_parse_webapp_init_data(config.BOT_TOKEN, x_telegram_init_data)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Telegram signature")
    if time.time() - init_data.auth_date.timestamp() > INIT_DATA_MAX_AGE:
        raise HTTPException(status_code=401, detail="Session expired, reopen the app")
    if init_data.user is None:
        raise HTTPException(status_code=401, detail="No Telegram user")
    return init_data.user.id
