import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import aiohttp
from aiogram.types import Update
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse

from rimex import config
from rimex.clients.common import create_http_session
from rimex.domain.address import is_valid_address
from rimex.presentation.api.auth import get_telegram_user_id
from rimex.presentation.api.schemas import ScanRequest, ScanResponse
from rimex.presentation.ratelimit import SlidingWindowLimiter
from rimex.presentation.telegram.app import (
    create_bot,
    create_dispatcher,
    setup_menu_button,
    validate_webapp_url,
)
from rimex.services.scanner import scan_solana_token

WEBHOOK_PATH = "/telegram/webhook"
WEBAPP_INDEX = Path(__file__).resolve().parents[3] / "webapp" / "index.html"

logger = logging.getLogger("rimex.api")

limiter = SlidingWindowLimiter(limit=5, period=60)


def webhook_enabled() -> bool:
    return bool(config.WEBHOOK_SECRET and config.PUBLIC_URL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not config.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set. It is required to verify Telegram users.")
    webapp_url = validate_webapp_url(config.WEBAPP_URL)
    app.state.http_session = create_http_session()
    app.state.bot = create_bot(config.BOT_TOKEN)
    app.state.dispatcher = create_dispatcher(app.state.http_session, webapp_url)

    if webhook_enabled():
        await app.state.bot.set_webhook(
            url=f"{config.PUBLIC_URL}{WEBHOOK_PATH}",
            secret_token=config.WEBHOOK_SECRET,
            allowed_updates=app.state.dispatcher.resolve_used_update_types(),
        )
        await setup_menu_button(app.state.bot, webapp_url)
        logger.info("Telegram webhook set to %s%s", config.PUBLIC_URL, WEBHOOK_PATH)

    yield

    await app.state.bot.session.close()
    await app.state.http_session.close()


app = FastAPI(title="Rimex X-Ray API", lifespan=lifespan)


def get_http_session(request: Request) -> aiohttp.ClientSession:
    return request.app.state.http_session


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(WEBAPP_INDEX)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/scan", response_model=ScanResponse)
async def scan(
    body: ScanRequest,
    user_id: Annotated[int, Depends(get_telegram_user_id)],
    http_session: Annotated[aiohttp.ClientSession, Depends(get_http_session)],
) -> ScanResponse:
    address = body.address.strip()
    if not is_valid_address(address):
        raise HTTPException(status_code=422, detail="Invalid Solana address")

    retry_after = limiter.hit(user_id)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail=f"Too many requests. Try again in {retry_after}s",
            headers={"Retry-After": str(retry_after)},
        )

    report = await scan_solana_token(address, http_session)
    return ScanResponse.from_report(report)


@app.post(WEBHOOK_PATH, include_in_schema=False)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
) -> dict[str, bool]:
    if not config.WEBHOOK_SECRET:
        raise HTTPException(status_code=404)
    if not x_telegram_bot_api_secret_token or not hmac.compare_digest(
        x_telegram_bot_api_secret_token, config.WEBHOOK_SECRET
    ):
        raise HTTPException(status_code=403)

    bot = request.app.state.bot
    update = Update.model_validate(await request.json(), context={"bot": bot})
    try:
        await request.app.state.dispatcher.feed_update(bot, update)
    except Exception:
        logger.exception("Failed to handle Telegram update %s", update.update_id)
    return {"ok": True}
