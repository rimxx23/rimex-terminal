import asyncio
import time
from decimal import Decimal, DecimalException
from typing import Annotated, Literal

import aiohttp
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request, Response
from pydantic import BaseModel, Field, model_validator
from starlette.concurrency import run_in_threadpool

from rimex.clients.quotes import CANDLE_INTERVALS, fetch_candles, stream_quotes
from rimex.domain.trading import PRICE_SCALE, SIZE_SCALE, TradeRejected, units
from rimex.presentation.api.web_auth import get_exchange, require_web_user
from rimex.presentation.ratelimit import SlidingWindowLimiter
from rimex.services.accounts import WebUser
from rimex.services.exchange import Exchange


router = APIRouter(prefix="/api/trade", tags=["demo trade"])
writes = SlidingWindowLimiter(limit=40, period=60)


class OrderRequest(BaseModel):
    side: Literal["buy", "sell"]
    kind: Literal["limit", "market"] = "limit"
    price: Decimal | None = Field(default=None, gt=0, le=100_000, max_digits=8, decimal_places=2)
    size: Decimal = Field(gt=0, le=1000, max_digits=7, decimal_places=3)

    @model_validator(mode="after")
    def validate_order_price(self):
        if (self.kind == "limit") != (self.price is not None):
            raise ValueError("A price is required only for a limit order.")
        return self


def enforce(limiter: SlidingWindowLimiter, identity: str) -> None:
    if retry := limiter.hit(identity):
        raise HTTPException(429, "Too many requests. Try again shortly.", headers={"Retry-After": str(retry)})


async def exchange_for(request: Request) -> Exchange:
    state = request.app.state
    exchange = await get_exchange(request)
    if state.quote_task is None or state.quote_task.done():
        async def on_quote(bid, ask, source):
            await run_in_threadpool(state.exchange.update_quote, bid, ask, source)

        state.quote_task = asyncio.create_task(stream_quotes(state.http_session, on_quote))
    return exchange


def require_trade_header(
    user: Annotated[WebUser, Depends(require_web_user)],
    x_rimex_trade: Annotated[str | None, Header()] = None,
) -> None:
    if x_rimex_trade != "1":
        raise HTTPException(403, "Missing trading request header.")


@router.get("")
async def snapshot(
    response: Response,
    user: Annotated[WebUser, Depends(require_web_user)],
    exchange: Annotated[Exchange, Depends(exchange_for)],
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return await run_in_threadpool(exchange.snapshot, user.account)


@router.get("/candles")
async def candles(
    interval: Literal["1m", "5m", "15m"],
    request: Request,
    user: Annotated[WebUser, Depends(require_web_user)],
) -> dict:
    state = request.app.state
    async with state.candle_locks[interval]:
        expires, data, stale = state.candles.get(interval, (0.0, None, False))
        if time.monotonic() >= expires:
            try:
                data = await fetch_candles(state.http_session, interval)
                stale = False
            except (aiohttp.ClientError, OSError, ValueError, TypeError, KeyError, IndexError, DecimalException):
                stale = True
            state.candles[interval] = (time.monotonic() + 8, data, stale)
    if data is None:
        raise HTTPException(503, "Chart data is temporarily unavailable.")
    return {"interval": interval, "seconds": CANDLE_INTERVALS[interval], "candles": data, "stale": stale}



@router.post("/orders", dependencies=[Depends(require_trade_header)], status_code=201)
async def place(
    body: OrderRequest,
    user: Annotated[WebUser, Depends(require_web_user)],
    exchange: Annotated[Exchange, Depends(exchange_for)],
) -> dict:
    enforce(writes, user.account)
    try:
        price = units(body.price, PRICE_SCALE, 100_000) if body.price is not None else None
        size = units(body.size, SIZE_SCALE, 1000)
        return await run_in_threadpool(exchange.place, user.account, body.side, price, size)
    except TradeRejected as error:
        raise HTTPException(409, str(error)) from None


@router.delete("/orders/{order_id}", dependencies=[Depends(require_trade_header)])
async def cancel(
    order_id: Annotated[int, Path(ge=1, le=2**63 - 1)],
    user: Annotated[WebUser, Depends(require_web_user)],
    exchange: Annotated[Exchange, Depends(exchange_for)],
) -> dict:
    enforce(writes, user.account)
    if not await run_in_threadpool(exchange.cancel, user.account, order_id):
        raise HTTPException(404, "Open order not found.")
    return {"cancelled": True}
