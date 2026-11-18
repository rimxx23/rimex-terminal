from fastapi.testclient import TestClient

from rimex import config
from rimex.presentation.api import app as api


def test_website_does_not_expose_telegram_routes(monkeypatch):
    monkeypatch.setattr(config, "BOT_TOKEN", "")
    monkeypatch.setattr(config, "PUBLIC_URL", "https://rimex.example")
    monkeypatch.setattr(config, "WEBHOOK_SECRET", "unused-test-secret")

    with TestClient(api.app) as client:
        assert client.get("/health").status_code == 200
        assert client.post("/telegram/webhook", json={}).status_code == 404
        assert client.post("/api/scan", json={}).status_code == 404
