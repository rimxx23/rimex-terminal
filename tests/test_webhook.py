import pytest
from aiogram import Bot
from fastapi.testclient import TestClient

from rimex import config
from rimex.presentation.api import app as api

SECRET = "test-webhook-secret"

UPDATE = {
    "update_id": 1001,
    "message": {
        "message_id": 1,
        "date": 1700000000,
        "chat": {"id": 42, "type": "private"},
        "from": {"id": 42, "is_bot": False, "first_name": "Test"},
        "text": "/start",
    },
}


class FakeDispatcher:
    def __init__(self, error: Exception | None = None) -> None:
        self.updates = []
        self.error = error

    async def feed_update(self, bot, update):
        self.updates.append(update)
        if self.error:
            raise self.error


@pytest.fixture
def client():
    with TestClient(api.app) as test_client:
        yield test_client


@pytest.fixture
def webhook_client(monkeypatch, client):
    monkeypatch.setattr(config, "WEBHOOK_SECRET", SECRET)
    dispatcher = FakeDispatcher()
    client.app.state.dispatcher = dispatcher
    return client, dispatcher


def post_update(client, secret=None, payload=UPDATE):
    headers = {} if secret is None else {"X-Telegram-Bot-Api-Secret-Token": secret}
    return client.post(api.WEBHOOK_PATH, json=payload, headers=headers)


def test_webhook_disabled_without_secret(client):
    assert post_update(client, secret="anything").status_code == 404


def test_webhook_rejects_missing_secret(webhook_client):
    client, dispatcher = webhook_client

    assert post_update(client).status_code == 403
    assert dispatcher.updates == []


def test_webhook_rejects_wrong_secret(webhook_client):
    client, dispatcher = webhook_client

    assert post_update(client, secret="guess").status_code == 403
    assert dispatcher.updates == []


def test_webhook_feeds_update_to_dispatcher(webhook_client):
    client, dispatcher = webhook_client

    response = post_update(client, secret=SECRET)

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert len(dispatcher.updates) == 1
    assert dispatcher.updates[0].update_id == 1001
    assert dispatcher.updates[0].message.text == "/start"


def test_handler_error_still_returns_200(webhook_client):
    client, _ = webhook_client
    client.app.state.dispatcher = FakeDispatcher(error=RuntimeError("boom"))

    response = post_update(client, secret=SECRET)

    assert response.status_code == 200


def test_lifespan_registers_webhook_and_menu(monkeypatch):
    calls = {}

    async def fake_set_webhook(self, url, secret_token, allowed_updates, **kwargs):
        calls["webhook"] = (url, secret_token, set(allowed_updates))
        return True

    async def fake_set_menu(self, menu_button, **kwargs):
        calls["menu"] = menu_button.web_app.url
        return True

    monkeypatch.setattr(Bot, "set_webhook", fake_set_webhook)
    monkeypatch.setattr(Bot, "set_chat_menu_button", fake_set_menu)
    monkeypatch.setattr(config, "PUBLIC_URL", "https://rimex.onrender.com")
    monkeypatch.setattr(config, "WEBAPP_URL", "https://rimex.onrender.com")
    monkeypatch.setattr(config, "WEBHOOK_SECRET", SECRET)

    with TestClient(api.app):
        pass

    url, secret, updates = calls["webhook"]
    assert url == "https://rimex.onrender.com/telegram/webhook"
    assert secret == SECRET
    assert updates == {"message", "callback_query"}
    assert calls["menu"] == "https://rimex.onrender.com"
