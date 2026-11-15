import hmac
import logging
import os
import time
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

import aiohttp
from aiogram.types import Update
from aiogram.utils.web_app import safe_parse_webapp_init_data
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from bot import create_bot, create_dispatcher, setup_menu_button, validate_webapp_url
from ratelimit import SlidingWindowLimiter
from scanner import (
    TokenReport,
    create_http_session,
    is_valid_address,
    lp_risk_level,
    scan_solana_token,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
PUBLIC_URL = (os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
WEBAPP_URL = os.getenv("WEBAPP_URL") or PUBLIC_URL or None
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
WEBHOOK_PATH = "/telegram/webhook"
INIT_DATA_MAX_AGE = 24 * 60 * 60
WEBAPP_INDEX = Path(__file__).parent / "webapp" / "index.html"

logger = logging.getLogger("rimex.api")

limiter = SlidingWindowLimiter(limit=5, period=60)


class ScanRequest(BaseModel):
    address: str


class ScanResponse(BaseModel):
    address: str
    symbol: str | None
    name: str | None
    price_usd: Decimal | None
    liquidity_usd: Decimal | None
    volume_24h: Decimal | None
    market_source: str | None
    authorities_loaded: bool
    mint_authority: str | None
    freeze_authority: str | None
    lp_locked_pct: Decimal | None
    lp_level: Literal["safe", "warning", "danger"] | None
    risk_score: int | None
    risks: list[str]
    errors: list[str]
    elapsed: float

    @classmethod
    def from_report(cls, report: TokenReport) -> "ScanResponse":
        return cls(
            **vars(report),
            lp_level=lp_risk_level(report.lp_locked_pct),
        )


def webhook_enabled() -> bool:
    return bool(WEBHOOK_SECRET and PUBLIC_URL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set. It is required to verify Telegram users.")
    webapp_url = validate_webapp_url(WEBAPP_URL)
    app.state.http_session = create_http_session()
    app.state.bot = create_bot(BOT_TOKEN)
    app.state.dispatcher = create_dispatcher(app.state.http_session, webapp_url)

    if webhook_enabled():
        await app.state.bot.set_webhook(
            url=f"{PUBLIC_URL}{WEBHOOK_PATH}",
            secret_token=WEBHOOK_SECRET,
            allowed_updates=app.state.dispatcher.resolve_used_update_types(),
        )
        await setup_menu_button(app.state.bot, webapp_url)
        logger.info("Telegram webhook set to %s%s", PUBLIC_URL, WEBHOOK_PATH)

    yield

    await app.state.bot.session.close()
    await app.state.http_session.close()


app = FastAPI(title="Rimex X-Ray API", lifespan=lifespan)


def get_http_session(request: Request) -> aiohttp.ClientSession:
    return request.app.state.http_session


def get_telegram_user_id(
    x_telegram_init_data: Annotated[str | None, Header()] = None,
) -> int:
    if not x_telegram_init_data:
        raise HTTPException(status_code=401, detail="Open this app from Telegram")
    try:
        init_data = safe_parse_webapp_init_data(BOT_TOKEN, x_telegram_init_data)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Telegram signature")
    if time.time() - init_data.auth_date.timestamp() > INIT_DATA_MAX_AGE:
        raise HTTPException(status_code=401, detail="Session expired, reopen the app")
    if init_data.user is None:
        raise HTTPException(status_code=401, detail="No Telegram user")
    return init_data.user.id


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
    if not WEBHOOK_SECRET:
        raise HTTPException(status_code=404)
    if not x_telegram_bot_api_secret_token or not hmac.compare_digest(
        x_telegram_bot_api_secret_token, WEBHOOK_SECRET
    ):
        raise HTTPException(status_code=403)

    bot = request.app.state.bot
    update = Update.model_validate(await request.json(), context={"bot": bot})
    try:
        await request.app.state.dispatcher.feed_update(bot, update)
    except Exception:
        logger.exception("Failed to handle Telegram update %s", update.update_id)
    return {"ok": True}
