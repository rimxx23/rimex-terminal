from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from rimex import config
from rimex.domain.trading import TradeRejected
from rimex.presentation.api import app as api
from rimex.services.exchange import Exchange
from rimex.services.swaps import SwapLedger, SwapNotFound, SWAP_TTL


def test_settlement_is_atomic_and_repeatable(tmp_path):
    exchange = Exchange(tmp_path / "swaps.sqlite3")
    exchange.create_account("owner")
    exchange.create_account("other")
    ledger = SwapLedger(exchange)
    quote = ledger.create("owner", "SOL", 100, 730_000)
    assert quote["min_output"] == "7.2635"
    with pytest.raises(SwapNotFound):
        ledger.settle("other", quote["id"], 730_000)
    with pytest.raises(TradeRejected, match="below the minimum"):
        ledger.settle("owner", quote["id"], 720_000)
    assert ledger.snapshot("owner")["balances"] == {"SOL": "5", "USDT": "10000"}

    with ThreadPoolExecutor(2) as workers:
        results = list(workers.map(lambda _: ledger.settle("owner", quote["id"], 729_000), range(2)))
    assert results[0] == results[1]
    assert ledger.snapshot("owner") == {
        "balances": {"SOL": "4.9", "USDT": "10007.29"},
        "history": [results[0]],
    }
    assert ledger.snapshot("other")["history"] == []


def test_uses_available_balance_and_refuses_expired_quote(tmp_path, monkeypatch):
    exchange = Exchange(tmp_path / "swaps.sqlite3")
    exchange.create_account("owner")
    clock = [100.0]
    monkeypatch.setattr("rimex.services.swaps.time.time", lambda: clock[0])
    exchange.update_quote(7300, 7310, "test")
    order = exchange.place("owner", "buy", 5000, 200_000)
    ledger = SwapLedger(exchange)
    quote = ledger.create("owner", "USDT", 730_000, 100)

    with pytest.raises(TradeRejected, match="Insufficient"):
        ledger.settle("owner", quote["id"], 100)
    assert exchange.cancel("owner", order["id"])
    clock[0] += SWAP_TTL
    with pytest.raises(TradeRejected, match="expired"):
        ledger.settle("owner", quote["id"], 100)
    assert ledger.snapshot("owner")["balances"] == {"SOL": "5", "USDT": "10000"}


def test_auth_refresh_and_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DEMO_DB_PATH", tmp_path / "swaps.sqlite3")
    headers = {"X-Rimex-Request": "1"}
    with TestClient(api.app) as client:
        assert client.get("/swap", follow_redirects=False).status_code == 303
        assert client.get("/api/swap").status_code == 401
        assert client.post("/api/swap/quotes", json={"asset": "SOL", "amount": "0.1"}).status_code == 401
        client.post(
            "/api/auth/register", json={"username": "swapper", "password": "test-password"},
            headers=headers,
        ).raise_for_status()
        calls = []

        async def output(asset, amount):
            calls.append((asset, amount))
            return 100 if asset == "USDT" else 730_000

        monkeypatch.setattr(client.app.state.jupiter, "output", output)
        assert client.get("/swap").status_code == 200
        result = client.post("/api/swap/quotes", json={"asset": "USDT", "amount": "7.3"}, headers=headers)
        assert result.status_code == 201
        assert result.json()["output_asset"] == "SOL"
        endpoint = f"/api/swap/quotes/{result.json()['id']}/confirm"
        assert client.post(endpoint).status_code == 403
        first = client.post(endpoint, headers=headers)
        again = client.post(endpoint, headers=headers)
        assert first.status_code == again.status_code == 200
        assert first.json() == again.json()
        assert client.get("/api/swap").json()["balances"] == {"SOL": "5.1", "USDT": "9992.7"}
        assert len(calls) == 2 and calls == [("USDT", 730_000), ("USDT", 730_000)]
