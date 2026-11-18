import asyncio

import pytest
from fastapi.testclient import TestClient

from rimex import config
from rimex.presentation.api import app as api, trading
from rimex.services.exchange import Exchange
from rimex.services.portfolio import Portfolio
from rimex.services.swaps import SwapLedger


@pytest.fixture
def ledger(tmp_path):
    exchange = Exchange(tmp_path / "portfolio.sqlite3")
    exchange.create_account("owner")
    exchange.create_account("other")
    return exchange, SwapLedger(exchange), Portfolio(exchange)


def test_swap_purchase_and_order_book_sale_share_cost_basis(ledger):
    exchange, swaps, portfolio = ledger
    exchange.update_quote(7290, 7310, "test")
    opening = portfolio.snapshot("owner", 25, 0)
    assert opening["starting_sol_price"] == "73"
    assert opening["equity"] == "10365"

    purchase = swaps.create("owner", "USDT", 7_500_000, 1000)
    swaps.settle("owner", purchase["id"], 1000)
    exchange.update_quote(7900, 7910, "test")
    exchange.place("owner", "sell", None, 1000)
    summary = portfolio.snapshot("owner", 25, 0)

    assert summary["starting_price_source"] == "first_portfolio_quote"
    assert summary["balances"] == {"SOL": "5", "USDT": "10004"}
    assert summary["average_price"] == "73.33333"
    assert summary["realized_pnl"] == "5.66667"
    assert summary["unrealized_pnl"] == "28.58333"
    assert summary["equity"] == "10399.25"
    assert [row["source"] for row in summary["journal"]] == ["trade", "swap"]
    assert summary["journal"][0]["realized_pnl"] == "5.66667"
    assert portfolio.snapshot("owner", 1, 1)["journal"] == summary["journal"][1:]
    assert portfolio.snapshot("other", 25, 0)["journal"] == []

    exchange.place("owner", "sell", 8400, 1000)
    exchange.place("owner", "buy", 7100, 1000)
    with_reserves = portfolio.snapshot("owner", 25, 0)
    assert with_reserves == summary


def test_existing_activity_supplies_initial_basis_without_a_live_mark(ledger):
    _, swaps, portfolio = ledger
    purchase = swaps.create("owner", "USDT", 7_500_000, 1000)
    swaps.settle("owner", purchase["id"], 1000)

    summary = portfolio.snapshot("owner", 25, 0)
    assert summary["starting_price_source"] == "first_operation"
    assert summary["starting_sol_price"] == "75"
    assert summary["average_price"] == "75"
    assert summary["realized_pnl"] == "0"
    assert summary["equity"] is summary["unrealized_pnl"] is None


def test_portfolio_page_and_api_require_session(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DEMO_DB_PATH", tmp_path / "portfolio.sqlite3")

    async def fake_feed(session, on_quote):
        await on_quote(7290, 7310, "test")
        await asyncio.Event().wait()

    monkeypatch.setattr(trading, "stream_quotes", fake_feed)
    with TestClient(api.app) as client:
        redirect = client.get("/portfolio", follow_redirects=False)
        assert redirect.status_code == 303
        assert redirect.headers["location"] == "/login?next=%2Fportfolio"
        assert client.get("/api/portfolio").status_code == 401
        client.post(
            "/api/auth/register", headers={"X-Rimex-Request": "1"},
            json={"username": "portfolio", "password": "test-password"},
        ).raise_for_status()
        assert client.get("/portfolio").status_code == 200
        response = client.get("/api/portfolio")
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["balances"] == {"SOL": "5", "USDT": "10000"}
        assert response.json()["total_operations"] == 0
