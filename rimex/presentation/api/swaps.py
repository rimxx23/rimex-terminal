from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from rimex.clients.jupiter import QuoteUnavailable
from rimex.domain.trading import Asset, TradeRejected, units
from rimex.presentation.api.web_auth import get_exchange, require_web_header, require_web_user
from rimex.services.accounts import WebUser
from rimex.services.swaps import MAX_AMOUNTS, SCALES, SwapLedger, SwapNotFound


router = APIRouter(prefix="/api/swap", tags=["demo swap"])


class SwapRequest(BaseModel):
    asset: Asset
    amount: Decimal = Field(gt=0, le=100_000, max_digits=11, decimal_places=5)


async def get_ledger(request: Request) -> SwapLedger:
    state = request.app.state
    if state.swap_ledger is None:
        exchange = await get_exchange(request)
        async with state.exchange_lock:
            if state.swap_ledger is None:
                state.swap_ledger = await run_in_threadpool(SwapLedger, exchange)
    return state.swap_ledger


def require_swap_write(
    user: Annotated[WebUser, Depends(require_web_user)],
    header: Annotated[None, Depends(require_web_header)],
) -> WebUser:
    return user


@router.get("")
async def snapshot(
    response: Response,
    user: Annotated[WebUser, Depends(require_web_user)],
    ledger: Annotated[SwapLedger, Depends(get_ledger)],
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return await run_in_threadpool(ledger.snapshot, user.account)


@router.post("/quotes", status_code=201)
async def quote(
    body: SwapRequest,
    request: Request,
    user: Annotated[WebUser, Depends(require_swap_write)],
    ledger: Annotated[SwapLedger, Depends(get_ledger)],
) -> dict:
    if retry := request.app.state.swap_limiter.hit(user.account):
        raise HTTPException(429, "Too many quotes. Try again shortly.", headers={"Retry-After": str(retry)})
    try:
        amount = units(body.amount, SCALES[body.asset], MAX_AMOUNTS[body.asset])
        output = await request.app.state.jupiter.output(body.asset, amount)
        return await run_in_threadpool(ledger.create, user.account, body.asset, amount, output)
    except TradeRejected as error:
        raise HTTPException(422, str(error)) from None
    except QuoteUnavailable as error:
        raise HTTPException(503, str(error)) from None


@router.post("/quotes/{quote_id}/confirm")
async def confirm(
    quote_id: Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")],
    request: Request,
    user: Annotated[WebUser, Depends(require_swap_write)],
    ledger: Annotated[SwapLedger, Depends(get_ledger)],
) -> dict:
    try:
        async with request.app.state.swap_confirm_lock:
            details = await run_in_threadpool(ledger.prepare, user.account, quote_id)
            if isinstance(details, dict):
                return details
            if retry := request.app.state.swap_confirm_limiter.hit(user.account):
                raise HTTPException(429, "Too many confirmations. Try again shortly.", headers={"Retry-After": str(retry)})
            asset, amount = details
            output = await request.app.state.jupiter.output(asset, amount)
            return await run_in_threadpool(ledger.settle, user.account, quote_id, output)
    except SwapNotFound as error:
        raise HTTPException(404, str(error)) from None
    except TradeRejected as error:
        raise HTTPException(409, str(error)) from None
    except QuoteUnavailable as error:
        raise HTTPException(503, str(error)) from None
