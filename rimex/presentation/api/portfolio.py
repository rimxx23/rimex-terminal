from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from rimex.presentation.api.swaps import get_ledger
from rimex.presentation.api.trading import exchange_for
from rimex.presentation.api.web_auth import require_web_user
from rimex.services.accounts import WebUser
from rimex.services.exchange import Exchange
from rimex.services.portfolio import Portfolio
from rimex.services.swaps import SwapLedger


router = APIRouter(prefix="/api/portfolio", tags=["demo portfolio"])


async def get_portfolio(
    request: Request,
    exchange: Annotated[Exchange, Depends(exchange_for)],
    _ledger: Annotated[SwapLedger, Depends(get_ledger)],
) -> Portfolio:
    state = request.app.state
    if state.portfolio is None:
        async with state.exchange_lock:
            if state.portfolio is None:
                state.portfolio = await run_in_threadpool(Portfolio, exchange)
    return state.portfolio


@router.get("")
async def snapshot(
    response: Response,
    user: Annotated[WebUser, Depends(require_web_user)],
    portfolio: Annotated[Portfolio, Depends(get_portfolio)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return await run_in_threadpool(portfolio.snapshot, user.account, limit, offset)
