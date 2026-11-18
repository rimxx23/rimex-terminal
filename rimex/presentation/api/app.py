import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

import aiohttp
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from rimex import config
from rimex.clients.common import create_http_session
from rimex.clients.jupiter import JupiterQuotes
from rimex.clients.quotes import CANDLE_INTERVALS
from rimex.domain.address import is_valid_address
from rimex.presentation.api.portfolio import router as portfolio_router
from rimex.presentation.api.schemas import ScanRequest, ScanResponse
from rimex.presentation.api.swaps import router as swap_router
from rimex.presentation.api.trading import router as trading_router, start_quote_feed
from rimex.presentation.api.web_auth import optional_user, require_web_user, router as auth_router
from rimex.presentation.ratelimit import SlidingWindowLimiter
from rimex.services.accounts import WebUser
from rimex.services.exchange import Exchange
from rimex.services.scanner import scan_solana_token

WEBAPP_DIR = Path(__file__).resolve().parents[3] / "webapp"
WORKSPACE_PAGES = {
    "/": ("overview.html", "overview"),
    "/scanner": ("index.html", "scanner"),
    "/trade": ("trade.html", "trade"),
    "/swap": ("swap.html", "swap"),
    "/portfolio": ("portfolio.html", "portfolio"),
    "/profile": ("profile.html", "profile"),
}

web_limiter = SlidingWindowLimiter(limit=5, period=60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.exchange = None
    app.state.exchange_lock = asyncio.Lock()
    app.state.accounts = None
    app.state.register_limiter = SlidingWindowLimiter(limit=5, period=60)
    app.state.login_limiter = SlidingWindowLimiter(limit=10, period=60)
    app.state.password_slots = asyncio.Semaphore(4)
    app.state.quote_task = None
    app.state.candles = {}
    app.state.candle_locks = {interval: asyncio.Lock() for interval in CANDLE_INTERVALS}
    app.state.web_scan_slots = asyncio.Semaphore(10)
    app.state.http_session = create_http_session()
    app.state.jupiter = JupiterQuotes(app.state.http_session, config.JUPITER_API_KEY)
    app.state.swap_ledger = None
    app.state.portfolio = None
    app.state.swap_confirm_lock = asyncio.Lock()
    app.state.swap_limiter = SlidingWindowLimiter(limit=12, period=60)
    app.state.swap_confirm_limiter = SlidingWindowLimiter(limit=12, period=60)
    try:
        if config.DEMO_DB_PATH.is_file():
            exchange = await run_in_threadpool(Exchange, config.DEMO_DB_PATH)
            app.state.exchange = exchange
            if await run_in_threadpool(exchange.has_active_exits):
                start_quote_feed(app, exchange)
        yield
    finally:
        if app.state.quote_task is not None:
            app.state.quote_task.cancel()
            await asyncio.gather(app.state.quote_task, return_exceptions=True)
        await app.state.http_session.close()


class WebsiteAssets(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app = FastAPI(title="Rimex Terminal", lifespan=lifespan)
app.mount("/static", WebsiteAssets(directory=WEBAPP_DIR), name="static")
app.include_router(auth_router)
app.include_router(trading_router)
app.include_router(swap_router)
app.include_router(portfolio_router)


@app.exception_handler(RequestValidationError)
async def validate_request(request: Request, error: RequestValidationError):
    if request.url.path.rstrip("/") in {"/api/auth/register", "/api/trade/register", "/api/auth/login"}:
        return JSONResponse({"detail": "Check your username and password."}, status_code=422)
    return await request_validation_exception_handler(request, error)


def get_http_session(request: Request) -> aiohttp.ClientSession:
    return request.app.state.http_session


@app.get("/login", include_in_schema=False)
async def login_page() -> FileResponse:
    return FileResponse(WEBAPP_DIR / "login.html", headers={"Cache-Control": "no-store"})


@app.get("/", include_in_schema=False, response_model=None)
@app.get("/scanner", include_in_schema=False, response_model=None)
@app.get("/trade", include_in_schema=False, response_model=None)
@app.get("/swap", include_in_schema=False, response_model=None)
@app.get("/portfolio", include_in_schema=False, response_model=None)
@app.get("/profile", include_in_schema=False, response_model=None)
def workspace_page(
    request: Request, user: Annotated[WebUser | None, Depends(optional_user)],
) -> HTMLResponse | RedirectResponse:
    headers = {"Cache-Control": "no-store"}
    route = request.url.path
    legacy_scan_link = route == "/" and "address" in request.query_params
    target = "/scanner" if legacy_scan_link else route
    destination = f"{target}?{request.url.query}" if request.url.query else target
    if user is None:
        return RedirectResponse(f"/login?{urlencode({'next': destination})}", status_code=303, headers=headers)
    if legacy_scan_link:
        return RedirectResponse(destination, status_code=303, headers=headers)

    filename, section = WORKSPACE_PAGES[target]
    sidebar = (WEBAPP_DIR / "sidebar.html").read_text(encoding="utf-8")
    active = f'data-section="{section}"'
    sidebar = sidebar.replace(active, f'{active} aria-current="page"')
    page = (WEBAPP_DIR / filename).read_text(encoding="utf-8")
    return HTMLResponse(page.replace("<!-- workspace navigation -->", sidebar), headers=headers)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def scan_for(
    body: ScanRequest, identity: int | str, throttle: SlidingWindowLimiter,
    http_session: aiohttp.ClientSession,
) -> ScanResponse:
    address = body.address.strip()
    if not is_valid_address(address):
        raise HTTPException(status_code=422, detail="Invalid Solana address")

    retry_after = throttle.hit(identity)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail=f"Too many requests. Try again in {retry_after}s",
            headers={"Retry-After": str(retry_after)},
        )

    report = await scan_solana_token(address, http_session)
    return ScanResponse.from_report(report)


@app.post("/api/web/scan", response_model=ScanResponse, dependencies=[Depends(require_web_user)])
async def web_scan(
    body: ScanRequest,
    request: Request,
    http_session: Annotated[aiohttp.ClientSession, Depends(get_http_session)],
) -> ScanResponse:
    identity = request.client.host if request.client else "unknown"
    slots = request.app.state.web_scan_slots
    if slots.locked():
        raise HTTPException(503, "Scanner is busy. Try again shortly.")
    async with slots:
        return await scan_for(body, identity, web_limiter, http_session)
