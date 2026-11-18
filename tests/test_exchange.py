import asyncio

import pytest
from fastapi.testclient import TestClient

from rimex import config
from rimex.clients.quotes import parse_quote
from rimex.domain.trading import TradeRejected
from rimex.presentation.api import app as api
from rimex.presentation.api import trading, web_auth
from rimex.presentation.ratelimit import SlidingWindowLimiter
from rimex.services.exchange import Exchange
from tests.conftest import BONK


def test_price_time_priority_partial_fill_and_release(tmp_path):
    db = tmp_path / "demo.sqlite3"
    exchange = Exchange(db)
    for user in ("buyer", "first", "second"):
        exchange.create_account(user)
    exchange.update_quote(9900, 10100, "test")
    first = exchange.place("first", "sell", 10_000, 1000)
    second = exchange.place("second", "sell", 10_000, 1000)
    exchange.place("buyer", "buy", 10_050, 1500)

    exchange = Exchange(db)
    assert exchange.snapshot("first")["orders"][0]["status"] == "filled"
    assert exchange.snapshot("second")["orders"][0]["remaining"] == "0.5"
    buyer = exchange.snapshot("buyer")
    assert buyer["wallet"] == {
        "usdt": "9850", "sol": "6.5", "locked_usdt": "0", "locked_sol": "0",
    }
    assert len(buyer["trades"]) == 2
    assert not exchange.cancel("buyer", second["id"])
    assert exchange.cancel("second", second["id"])
    assert exchange.snapshot("second")["wallet"]["sol"] == "4.5"
    assert not exchange.cancel("first", first["id"])


def test_maker_reprices_resting_orders_and_releases_price_improvement(tmp_path):
    exchange = Exchange(tmp_path / "demo.sqlite3")
    exchange.create_account("guest")
    exchange.update_quote(9900, 10100, "test")
    order = exchange.place("guest", "buy", 10_000, 2000)
    assert order["status"] == "open"
    assert exchange.snapshot("guest")["wallet"]["locked_usdt"] == "200"
    exchange.update_quote(9700, 9800, "test")
    snapshot = exchange.snapshot("guest")
    assert snapshot["orders"][0]["status"] == "filled"
    assert snapshot["wallet"]["usdt"] == "9804"
    assert snapshot["wallet"]["sol"] == "7"
    assert snapshot["trades"][0]["price"] == "98"


def test_stale_quotes_and_insufficient_balance_do_not_create_orders(tmp_path, monkeypatch):
    exchange = Exchange(tmp_path / "demo.sqlite3")
    exchange.create_account("guest")
    clock = [1.0]
    monkeypatch.setattr("rimex.services.exchange.time.time", lambda: clock[0])
    exchange.update_quote(9900, 10100, "test")
    with pytest.raises(TradeRejected, match="balance"):
        exchange.place("guest", "sell", 11_000, 6000)
    clock[0] += 20
    with pytest.raises(TradeRejected, match="quotes"):
        exchange.place("guest", "buy", 10_000, 1000)
    assert exchange.snapshot("guest")["orders"] == []


def test_quote_rounds_outward():
    assert parse_quote("73.353", "73.357") == (7335, 7336)


def test_web_scan_without_telegram_and_rate_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DEMO_DB_PATH", tmp_path / "demo.sqlite3")
    monkeypatch.setattr(config, "BOT_TOKEN", "")
    monkeypatch.setattr(api, "web_limiter", SlidingWindowLimiter(1, 60))

    async def scan(address, _session):
        from rimex.domain.models import TokenReport
        return TokenReport(address=address, symbol="BONK")

    monkeypatch.setattr(api, "scan_solana_token", scan)
    with TestClient(api.app) as client:
        client.post(
            "/api/auth/register", headers={"X-Rimex-Request": "1"},
            json={"username": "scanner", "password": "demo-password"},
        ).raise_for_status()
        assert client.post("/api/web/scan", json={"address": BONK}).json()["symbol"] == "BONK"
        response = client.post("/api/web/scan", json={"address": BONK})
        assert response.status_code == 429
        assert response.headers["Retry-After"]
        assert client.post("/api/scan", json={"address": BONK}).status_code == 404


def test_demo_browser_session_requires_trade_header_and_isolates_wallet(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DEMO_DB_PATH", tmp_path / "demo.sqlite3")

    async def fake_feed(session, on_quote):
        await on_quote(9900, 10100, "test")
        await asyncio.Event().wait()

    monkeypatch.setattr(trading, "stream_quotes", fake_feed)
    headers = {"X-Rimex-Trade": "1"}
    order = {"side": "buy", "price": "101.00", "size": "1.000"}
    def sign_up(client, username):
        return client.post(
            "/api/auth/register", headers={"X-Rimex-Request": "1"},
            json={"username": username, "password": "demo-password"},
        )

    with TestClient(api.app) as client:
        assert "HttpOnly" in sign_up(client, "first").headers["set-cookie"]
        assert client.get("/trade").status_code == 200
        initial = client.get("/api/trade")
        assert initial.json()["wallet"]["usdt"] == "10000"
        assert client.post("/api/trade/orders", json=order).status_code == 403

        client.app.state.exchange.update_quote(9900, 10100, "test")
        assert client.post("/api/trade/orders", headers=headers, json=order).json()["status"] == "filled"
        open_order = client.post(
            "/api/trade/orders", headers=headers, json={**order, "price": "98"}
        ).json()
        assert open_order["status"] == "open"
        assert client.get("/api/trade").json()["wallet"]["usdt"] == "9801"
        own_cookie = client.cookies.get(web_auth.COOKIE)
        client.cookies.clear()
        sign_up(client, "second").raise_for_status()
        assert client.get("/api/trade").json()["wallet"]["usdt"] == "10000"
        assert client.delete(f"/api/trade/orders/{open_order['id']}", headers=headers).status_code == 404
        client.cookies.clear()
        client.cookies.set(web_auth.COOKIE, own_cookie)
        assert client.delete(f"/api/trade/orders/{open_order['id']}", headers=headers).status_code == 200
        assert client.get("/api/trade").json()["wallet"]["usdt"] == "9899"


def test_market_order_fills_available_amount_and_releases_rest(tmp_path):
    exchange = Exchange(tmp_path / "market.sqlite3")
    exchange.create_account("buyer")
    exchange.update_quote(9900, 10100, "test")
    result = exchange.place("buyer", "buy", None, 8000)

    assert result["kind"] == "market"
    assert result["status"] == "cancelled"
    assert result["remaining"] == "3"
    snapshot = exchange.snapshot("buyer")
    assert snapshot["wallet"] == {
        "usdt": "9495", "sol": "10", "locked_usdt": "0", "locked_sol": "0",
    }
    assert snapshot["trades"][0]["price"] == "101"
    assert snapshot["trades"][0]["size"] == "5"
    assert snapshot["book"]["buy"][0]["price"] == "99"
    with pytest.raises(TradeRejected, match="No liquidity"):
        exchange.place("buyer", "buy", None, 1000)
    assert exchange.snapshot("buyer")["orders"] == [result]


def test_existing_orders_get_limit_kind(tmp_path):
    path = tmp_path / "existing.sqlite3"
    exchange = Exchange(path)
    exchange.create_account("buyer")
    exchange.update_quote(9900, 10100, "test")
    order = exchange.place("buyer", "buy", 9900, 1000)
    with exchange.transaction() as db:
        db.execute("ALTER TABLE orders DROP COLUMN kind")
    updated = Exchange(path)
    assert updated.snapshot("buyer")["orders"] == [order]


def test_candles_require_login_and_cache_by_interval(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DEMO_DB_PATH", tmp_path / "chart.sqlite3")
    calls = []

    async def candles(session, interval):
        calls.append(interval)
        return [{"time": 1800, "open": "100", "high": "103", "low": "99", "close": "102"}]

    monkeypatch.setattr(trading, "fetch_candles", candles)
    with TestClient(api.app) as client:
        assert client.get("/api/trade/candles?interval=1m").status_code == 401
        client.post(
            "/api/auth/register", headers={"X-Rimex-Request": "1"},
            json={"username": "chartuser", "password": "demo-password"},
        ).raise_for_status()
        for interval in ("1m", "1m", "15m"):
            result = client.get(f"/api/trade/candles?interval={interval}").json()
            assert result["interval"] == interval
            assert result["candles"][0]["close"] == "102"
        assert client.get("/api/trade/candles?interval=1d").status_code == 422
    assert calls == ["1m", "15m"]
