import hashlib
import hmac
import json
import os
import time
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from rimex.domain.models import TokenReport
from rimex.presentation.api import app as api
from rimex.presentation.ratelimit import SlidingWindowLimiter
from tests.conftest import BONK

BOT_TOKEN = os.environ["BOT_TOKEN"]


def sign_init_data(user_id: int = 42, auth_date: int | None = None, token: str = BOT_TOKEN) -> str:
    fields = {
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "AAH-test",
        "user": json.dumps({"id": user_id, "first_name": "Test"}),
    }
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


@pytest.fixture
def scanned_addresses(monkeypatch):
    addresses = []

    async def fake_scan(address, session=None):
        addresses.append(address)
        return TokenReport(
            address=address,
            symbol="Bonk",
            name="Bonk",
            price_usd=Decimal("0.000002357"),
            authorities_loaded=True,
            lp_locked_pct=Decimal("19.4"),
            elapsed=0.42,
        )

    monkeypatch.setattr(api, "scan_solana_token", fake_scan)
    return addresses


@pytest.fixture
def client(monkeypatch, scanned_addresses):
    monkeypatch.setattr(api, "limiter", SlidingWindowLimiter(limit=5, period=60))
    with TestClient(api.app) as test_client:
        yield test_client


def scan(client, address=BONK, init_data=None):
    headers = {} if init_data is None else {"X-Telegram-Init-Data": init_data}
    return client.post("/api/scan", json={"address": address}, headers=headers)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_index_serves_mini_app(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "RIMEX" in response.text


def test_scan_with_valid_signature(client, scanned_addresses):
    response = scan(client, init_data=sign_init_data())

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "Bonk"
    assert body["price_usd"] == "0.000002357"
    assert body["lp_level"] == "danger"
    assert scanned_addresses == [BONK]


def test_address_is_trimmed(client, scanned_addresses):
    response = scan(client, address=f"  {BONK}\n", init_data=sign_init_data())

    assert response.status_code == 200
    assert scanned_addresses == [BONK]


def test_missing_init_data_is_rejected(client, scanned_addresses):
    response = scan(client)

    assert response.status_code == 401
    assert scanned_addresses == []


def test_signature_from_another_bot_is_rejected(client, scanned_addresses):
    forged = sign_init_data(token="999999:SOMEONE-ELSES-BOT")

    response = scan(client, init_data=forged)

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid Telegram signature"
    assert scanned_addresses == []


def test_tampered_user_id_is_rejected(client, scanned_addresses):
    tampered = sign_init_data(user_id=42).replace("%22id%22%3A+42", "%22id%22%3A+1")

    response = scan(client, init_data=tampered)

    assert response.status_code == 401
    assert scanned_addresses == []


def test_expired_init_data_is_rejected(client, scanned_addresses):
    two_days_ago = int(time.time()) - 2 * 24 * 60 * 60

    response = scan(client, init_data=sign_init_data(auth_date=two_days_ago))

    assert response.status_code == 401
    assert response.json()["detail"] == "Session expired, reopen the app"


def test_invalid_address_returns_422(client, scanned_addresses):
    response = scan(client, address="abc", init_data=sign_init_data())

    assert response.status_code == 422
    assert scanned_addresses == []


def test_rate_limit_per_user(client):
    for _ in range(5):
        assert scan(client, init_data=sign_init_data(user_id=7)).status_code == 200

    blocked = scan(client, init_data=sign_init_data(user_id=7))
    other_user = scan(client, init_data=sign_init_data(user_id=8))

    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0
    assert other_user.status_code == 200


def test_mini_app_assets_are_served(client):
    page = client.get("/")
    script = client.get("/static/js/main.js")
    styles = client.get("/static/css/styles.css")

    assert '<script type="module" src="/static/js/main.js">' in page.text
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
    assert styles.status_code == 200
    assert "text/css" in styles.headers["content-type"]


def test_static_does_not_expose_files_outside_webapp(client):
    assert client.get("/static/../.env").status_code == 404
    assert client.get("/static/%2e%2e/.env").status_code == 404
