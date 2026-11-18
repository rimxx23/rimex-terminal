import asyncio
import threading

import pytest
from fastapi.testclient import TestClient

from rimex import config
from rimex.domain.trading import TradeRejected
from rimex.presentation.api import app as api, trading
from rimex.services.exchange import Exchange
from rimex.services.portfolio import Portfolio
from rimex.services.swaps import SwapLedger


def test_stop_reserves_once_and_labels_realized_loss(tmp_path):
    exchange = Exchange(tmp_path / "exits.sqlite3")
    exchange.create_account("owner")
    exchange.create_account("other")
    SwapLedger(exchange)
    portfolio = Portfolio(exchange)

    exchange.update_quote(7399, 7401, "test")
    opening = portfolio.snapshot("owner", 10, 0)
    plan = exchange.protect("owner", 1000, 7200, 7800)
    assert exchange.snapshot("owner")["wallet"]["sol"] == "4"
    assert exchange.snapshot("owner")["wallet"]["locked_sol"] == "1"
    assert portfolio.snapshot("owner", 10, 0) == opening
    assert not exchange.cancel_exit("other", plan["id"])
    with pytest.raises(TradeRejected, match="Insufficient"):
        exchange.place("owner", "sell", None, 4001)

    exchange.update_quote(7190, 7200, "test")
    exchange.update_quote(7900, 7901, "test")
    result = exchange.snapshot("owner")
    assert result["exits"][0]["status"] == "filled"
    assert result["exits"][0]["trigger"] == "stop_loss"
    assert result["wallet"]["locked_sol"] == "0"
    assert len(result["trades"]) == 1
    assert result["trades"][0]["price"] == "71.9"
    assert not exchange.cancel_exit("owner", plan["id"])
    assert portfolio.snapshot("owner", 10, 0)["journal"][0]["trigger"] == "stop_loss"
    assert portfolio.snapshot("owner", 10, 0)["realized_pnl"] == "-2.1"


def test_triggered_partial_exit_keeps_remainder_reserved(tmp_path):
    exchange = Exchange(tmp_path / "exits.sqlite3")
    exchange.create_account("owner")
    exchange.update_quote(7399, 7401, "test")
    exchange.place("owner", "buy", None, 4000)
    plan = exchange.protect("owner", 8000, 7200, 7800)

    exchange.update_quote(7800, 7801, "test")
    pending = exchange.snapshot("owner")
    assert pending["exits"][0]["trigger"] == "take_profit"
    assert pending["exits"][0]["status"] == "triggered"
    assert pending["exits"][0]["remaining"] == "3"
    assert pending["wallet"]["locked_sol"] == "3"
    assert pending["wallet"]["sol"] == "1"
    assert exchange.cancel_exit("owner", plan["id"])
    assert not exchange.cancel_exit("owner", plan["id"])
    exchange.update_quote(7100, 7101, "test")
    assert exchange.snapshot("owner")["wallet"]["sol"] == "4"
    assert exchange.snapshot("owner")["wallet"]["locked_sol"] == "0"


def test_restart_runs_pending_plan_without_an_http_request(tmp_path, monkeypatch):
    path = tmp_path / "exits.sqlite3"
    exchange = Exchange(path)
    exchange.create_account("owner")
    exchange.create_account("other")
    exchange.update_quote(7399, 7401, "test")
    exchange.place("other", "sell", 7700, 5000)
    exchange.protect("owner", 1000, 7200, 7800)
    exchange.update_quote(7800, 7801, "test")
    before = exchange.snapshot("owner")
    assert before["exits"][0]["status"] == "triggered"
    assert before["trades"] == []

    refreshed = threading.Event()

    async def feed(session, on_quote):
        await on_quote(7100, 7101, "after restart")
        refreshed.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(config, "DEMO_DB_PATH", path)
    monkeypatch.setattr(trading, "stream_quotes", feed)
    with TestClient(api.app):
        assert refreshed.wait(3)
        after = exchange.snapshot("owner")
        assert after["exits"][0]["status"] == "filled"
        assert after["exits"][0]["trigger"] == "take_profit"
        assert after["trades"][0]["price"] == "71"
        assert after["wallet"]["locked_sol"] == "0"


def test_exit_api_requires_auth_and_valid_levels(tmp_path, monkeypatch):
    path = tmp_path / "exits.sqlite3"
    monkeypatch.setattr(config, "DEMO_DB_PATH", path)

    async def idle_feed(session, on_quote):
        await asyncio.Event().wait()

    monkeypatch.setattr(trading, "stream_quotes", idle_feed)
    auth = {"X-Rimex-Request": "1"}
    trade = {"X-Rimex-Trade": "1"}
    payload = {"size": "0.5", "stop": "72", "target": "78"}
    with TestClient(api.app) as client:
        assert client.post("/api/trade/exits", json=payload, headers=trade).status_code == 401
        client.post("/api/auth/register", headers=auth, json={
            "username": "owner", "password": "test-password",
        }).raise_for_status()
        api.app.state.exchange.update_quote(7399, 7401, "test")
        assert client.post("/api/trade/exits", json=payload).status_code == 403
        assert client.post("/api/trade/exits", json={**payload, "stop": "75"}, headers=trade).status_code == 409
        response = client.post("/api/trade/exits", json=payload, headers=trade)
        assert response.status_code == 201
        assert client.get("/api/trade").json()["wallet"]["locked_sol"] == "0.5"
        endpoint = f"/api/trade/exits/{response.json()['id']}"
        assert client.delete(endpoint, headers=trade).status_code == 200
        assert client.get("/api/trade").json()["wallet"]["locked_sol"] == "0"
