from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from rimex import config
from rimex.domain.models import TokenReport
from rimex.presentation.api import app as api
from rimex.presentation.ratelimit import SlidingWindowLimiter
from tests.conftest import BONK

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
def client(monkeypatch, scanned_addresses, tmp_path):
    monkeypatch.setattr(api, "web_limiter", SlidingWindowLimiter(limit=5, period=60))
    monkeypatch.setattr(config, "DEMO_DB_PATH", tmp_path / "demo.sqlite3")
    with TestClient(api.app) as test_client:
        yield test_client


@pytest.fixture
def signed_in(client):
    client.post(
        "/api/auth/register", headers={"X-Rimex-Request": "1"},
        json={"username": "scanner", "password": "test-only-password"},
    ).raise_for_status()
    return client


def scan(client, address=BONK):
    return client.post("/api/web/scan", json={"address": address})


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_index_serves_website(signed_in):
    response = signed_in.get("/")

    assert response.status_code == 200
    assert "RIMEX" in response.text
    assert "telegram-web-app.js" not in response.text


def test_scan_with_a_session(signed_in, scanned_addresses):
    response = scan(signed_in)

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "Bonk"
    assert body["price_usd"] == "0.000002357"
    assert body["lp_level"] == "danger"
    assert scanned_addresses == [BONK]


def test_address_is_trimmed(signed_in, scanned_addresses):
    response = scan(signed_in, address=f"  {BONK}\n")

    assert response.status_code == 200
    assert scanned_addresses == [BONK]


def test_missing_session_is_rejected(client, scanned_addresses):
    response = scan(client)

    assert response.status_code == 401
    assert scanned_addresses == []


def test_login_redirect_preserves_deep_link(client):
    response = client.get(f"/?address={BONK}", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == f"/login?next=%2F%3Faddress%3D{BONK}"


def test_invalid_address_returns_422(signed_in, scanned_addresses):
    response = scan(signed_in, address="abc")

    assert response.status_code == 422
    assert scanned_addresses == []


def test_rate_limit_per_ip(signed_in):
    for _ in range(5):
        assert scan(signed_in).status_code == 200

    blocked = scan(signed_in)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0


def test_website_assets_are_served(signed_in):
    page = signed_in.get("/")
    script = signed_in.get("/static/js/main.js")
    styles = signed_in.get("/static/css/styles.css")

    assert '<script type="module" src="/static/js/main.js?v=3">' in page.text
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
    assert script.headers["cache-control"] == "no-cache"
    assert styles.status_code == 200
    assert "text/css" in styles.headers["content-type"]


def test_static_does_not_expose_files_outside_webapp(client):
    assert client.get("/static/../.env").status_code == 404
    assert client.get("/static/%2e%2e/.env").status_code == 404
