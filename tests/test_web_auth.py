import pytest
from fastapi.testclient import TestClient

from rimex import config
from rimex.presentation.api import app as api
from rimex.presentation.api import web_auth
from rimex.services.accounts import token_hash
from rimex.services.exchange import Exchange
from tests.conftest import BONK


HEADERS = {"X-Rimex-Request": "1"}
PASSWORD = "demo-password-938"


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DEMO_DB_PATH", tmp_path / "demo.sqlite3")
    with TestClient(api.app) as instance:
        yield instance


def credentials(username="Trader", password=PASSWORD):
    return {"username": username, "password": password}


def test_web_features_reject_anonymous_requests(client):
    assert client.get("/login").status_code == 200
    trade = client.get("/trade", follow_redirects=False)
    assert trade.status_code == 303
    assert trade.headers["location"] == "/login?next=%2Ftrade"
    assert client.post("/api/web/scan", json={"address": BONK}).status_code == 401
    assert client.get("/api/trade").status_code == 401
    assert client.post("/api/trade/orders", json={"side": "buy", "size": "1", "price": "10"}).status_code == 401
    assert client.delete("/api/trade/orders/1").status_code == 401
    assert client.app.state.quote_task is None


def test_register_login_and_logout_revoke_session(client):
    missing_header = client.post("/api/auth/register", json=credentials())
    assert missing_header.status_code == 403
    registered = client.post("/api/auth/register", headers=HEADERS, json=credentials())
    assert registered.status_code == 201
    assert registered.json() == {"username": "trader"}
    cookie = registered.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    original_token = client.cookies.get(web_auth.COOKIE)
    assert client.get("/trade", follow_redirects=False).status_code == 200
    assert client.get("/api/auth/me").json() == {"username": "trader"}
    assert client.post("/api/auth/register", headers=HEADERS, json=credentials("TRADER")).status_code == 409
    wrong = client.post("/api/auth/login", headers=HEADERS, json=credentials(password="wrong-password"))
    unknown = client.post("/api/auth/login", headers=HEADERS, json=credentials("unknown"))
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    logged_in = client.post("/api/auth/login", headers=HEADERS, json=credentials())
    assert logged_in.status_code == 200
    updated_token = client.cookies.get(web_auth.COOKIE)
    assert updated_token != original_token
    assert client.app.state.accounts.get_user(original_token) is None
    assert client.post("/api/auth/logout", headers=HEADERS).status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    client.cookies.set(web_auth.COOKIE, updated_token)
    assert client.get("/api/auth/me").status_code == 401


def test_registration_keeps_legacy_wallet_only_once(client):
    guest_cookie = "x" * 43
    exchange = Exchange(config.DEMO_DB_PATH)
    exchange.create_account(token_hash(guest_cookie))
    exchange.update_quote(9900, 10100, "test")
    exchange.place(token_hash(guest_cookie), "buy", 10_100, 1_000)
    client.cookies.set(web_auth.GUEST_COOKIE, guest_cookie, path="/api/trade")

    migrated = client.post("/api/trade/register", headers=HEADERS, json=credentials())
    assert migrated.status_code == 201
    user = client.app.state.accounts.get_user(client.cookies.get(web_auth.COOKIE))
    assert user.account == token_hash(guest_cookie)
    assert exchange.snapshot(user.account)["wallet"]["sol"] == "6"

    client.cookies.set(web_auth.GUEST_COOKIE, guest_cookie, path="/api/trade")
    registered = client.post("/api/trade/register", headers=HEADERS, json=credentials("another"))
    assert registered.status_code == 201
    other = client.app.state.accounts.get_user(client.cookies.get(web_auth.COOKIE))
    assert other.account != user.account
    assert exchange.snapshot(other.account)["wallet"]["sol"] == "5"


def test_expired_session_and_invalid_credentials_do_not_expose_password(client):
    weak_password = "abc123"
    response = client.post("/api/auth/register", headers=HEADERS, json=credentials(password=weak_password))
    assert response.status_code == 422
    assert weak_password not in response.text
    client.post("/api/auth/register", headers=HEADERS, json=credentials()).raise_for_status()
    with client.app.state.exchange.transaction() as db:
        assert db.execute("SELECT password_hash FROM web_users").fetchone()[0] != PASSWORD
        db.execute("UPDATE web_sessions SET expires_at = 0")
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/web/scan", json={"address": BONK}).status_code == 401
