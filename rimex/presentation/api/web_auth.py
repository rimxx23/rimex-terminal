from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from rimex import config
from rimex.presentation.ratelimit import SlidingWindowLimiter
from rimex.services.accounts import (
    DUMMY_HASH, SESSION_AGE, TOKEN_LENGTH, Accounts, WebUser, hash_password, verify_password,
)
from rimex.services.exchange import Exchange


router = APIRouter(tags=["web auth"])
COOKIE = "rimex_session"
GUEST_COOKIE = "rimex_demo"


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)


async def get_exchange(request: Request) -> Exchange:
    state = request.app.state
    if state.exchange is None:
        async with state.exchange_lock:
            if state.exchange is None:
                state.exchange = await run_in_threadpool(Exchange, config.DEMO_DB_PATH)
    return state.exchange


async def get_accounts(request: Request) -> Accounts:
    state = request.app.state
    if state.accounts is None:
        exchange = await get_exchange(request)
        async with state.exchange_lock:
            if state.accounts is None:
                state.accounts = await run_in_threadpool(Accounts, exchange)
    return state.accounts


async def optional_user(request: Request) -> WebUser | None:
    token = request.cookies.get(COOKIE, "")
    if len(token) != TOKEN_LENGTH:
        return None
    accounts = await get_accounts(request)
    return await run_in_threadpool(accounts.get_user, token)


async def require_web_user(user: Annotated[WebUser | None, Depends(optional_user)]) -> WebUser:
    if user is None:
        raise HTTPException(401, "Sign in to continue.", headers={"Cache-Control": "no-store"})
    return user


def require_web_header(x_rimex_request: Annotated[str | None, Header()] = None) -> None:
    if x_rimex_request != "1":
        raise HTTPException(403, "Missing browser request header.")


def limit_auth(request: Request, limiter: SlidingWindowLimiter) -> None:
    key = request.client.host if request.client else "unknown"
    if retry := limiter.hit(key):
        raise HTTPException(429, "Too many attempts. Try again shortly.", headers={"Retry-After": str(retry)})


def set_session(request: Request, response: Response, token: str) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        COOKIE, token, max_age=SESSION_AGE, httponly=True, samesite="lax",
        secure=request.url.scheme == "https", path="/",
    )


@router.post("/api/trade/register", include_in_schema=False, dependencies=[Depends(require_web_header)], status_code=201)
@router.post("/api/auth/register", dependencies=[Depends(require_web_header)], status_code=201)
async def register(body: Credentials, request: Request, response: Response) -> dict[str, str]:
    limit_auth(request, request.app.state.register_limiter)
    accounts = await get_accounts(request)
    async with request.app.state.password_slots:
        password_hash = await run_in_threadpool(hash_password, body.password)
    result = await run_in_threadpool(
        accounts.register, body.username.lower(), password_hash,
        request.cookies.get(GUEST_COOKIE, ""), request.cookies.get(COOKIE, ""),
    )
    if result is None:
        raise HTTPException(409, "This username is already taken.")
    user, token = result
    set_session(request, response, token)
    response.delete_cookie(GUEST_COOKIE, path="/api/trade")
    return {"username": user.username}


@router.post("/api/auth/login", dependencies=[Depends(require_web_header)])
async def login(body: Credentials, request: Request, response: Response) -> dict[str, str]:
    limit_auth(request, request.app.state.login_limiter)
    username = body.username.lower()
    accounts = await get_accounts(request)
    stored = await run_in_threadpool(accounts.get_password_hash, username)
    async with request.app.state.password_slots:
        valid = await run_in_threadpool(verify_password, body.password, stored or DUMMY_HASH)
    if not stored or not valid:
        raise HTTPException(401, "Invalid username or password.")
    token = await run_in_threadpool(accounts.create_session, username, request.cookies.get(COOKIE, ""))
    set_session(request, response, token)
    return {"username": username}


@router.get("/api/auth/me")
async def me(response: Response, user: Annotated[WebUser, Depends(require_web_user)]) -> dict[str, str]:
    response.headers["Cache-Control"] = "no-store"
    return {"username": user.username}


@router.post("/api/auth/logout", dependencies=[Depends(require_web_header)])
async def logout(request: Request, response: Response) -> dict[str, bool]:
    token = request.cookies.get(COOKIE, "")
    if len(token) == TOKEN_LENGTH:
        accounts = await get_accounts(request)
        await run_in_threadpool(accounts.logout, token)
    response.delete_cookie(COOKIE, path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True}
