from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin.crypto import CryptoService
from app.admin.key_repository import KeyRepository
from app.admin.provider_config_repository import ProviderConfigRepository
from app.admin.runtime import set_admin_runtime
from app.api.routes_admin import router
from app.config import settings
from app.providers.schwab import SchwabProvider


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "ADMIN_AUTH_ENABLED", False)
    key = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    key_repo = KeyRepository(str(tmp_path / "keys.db"), CryptoService(key))
    config_repo = ProviderConfigRepository(str(tmp_path / "keys.db"))
    set_admin_runtime(key_repository=key_repo, provider_config_repository=config_repo)

    async def noop_reload(repo):
        return None

    monkeypatch.setattr("app.api.routes_admin.registry.reload_from_config", noop_reload)
    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    set_admin_runtime()


def test_keys_and_credentials_metadata_only(client) -> None:
    response = client.post(
        "/api/admin/keys",
        json={"provider_name": "finnhub", "credential_name": "api_key", "value": "secret-key"},
    )
    assert response.status_code == 200

    credentials = client.get("/api/admin/credentials")

    assert credentials.status_code == 200
    body = credentials.json()
    slot = next(item for item in body if item["provider"] == "finnhub" and item["credential_name"] == "api_key")
    assert slot["set"] is True
    assert slot["masked_value"] == "configured"
    assert "secret-key" not in credentials.text


def test_unknown_credential_rejected(client) -> None:
    response = client.put("/api/admin/credentials/finnhub", json={"unknown_key": "value"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown credential: unknown_key for provider finnhub"


def test_provider_config_update_and_ibkr_gateway(client) -> None:
    response = client.put("/api/admin/providers/finnhub/config", json={"timeout_seconds": 10, "retry_count": 3})
    assert response.status_code == 200
    assert response.json()["timeout_seconds"] == 10
    assert response.json()["retry_count"] == 3

    gateway = client.put("/api/admin/providers/ibkr/gateway", json={"host": "192.168.1.10", "port": 4001})
    assert gateway.status_code == 200
    assert gateway.json()["connection_config"] == {"host": "192.168.1.10", "port": 4001}


def test_provider_config_validation(client) -> None:
    response = client.put("/api/admin/providers/schwab/config", json={"timeout_seconds": -1})

    assert response.status_code == 422


def test_schwab_auth_callback_saves_token_and_unpauses(client, monkeypatch) -> None:
    client.put("/api/admin/credentials/schwab", json={"api_key": "key", "app_secret": "secret"})
    saved = {}

    def fake_client_from_received_url(**kwargs):
        saved.update(kwargs)
        return SimpleNamespace(token={"access_token": "token"})

    provider = SchwabProvider()
    provider._paused = True
    monkeypatch.setattr("app.api.routes_admin.client_from_received_url", fake_client_from_received_url)
    monkeypatch.setitem(__import__("app.api.routes_admin", fromlist=["registry"]).registry._providers, "schwab", provider)

    response = client.post("/api/admin/schwab/auth/callback", json={"received_url": "https://callback?code=abc"})

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert saved["received_url"] == "https://callback?code=abc"
    assert provider._paused is False
    status = client.get("/api/admin/schwab/auth/status")
    assert status.json()["storage"] == "sqlite"


def test_alert_webhook_update_and_test(client, monkeypatch) -> None:
    response = client.put("/api/admin/alerts/webhook", json={"webhook_url": "https://hooks.example/test", "format": "slack"})
    assert response.status_code == 200

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json):
            assert url == "https://hooks.example/test"
            return SimpleNamespace(status_code=200)

    monkeypatch.setattr("app.api.routes_admin.httpx.AsyncClient", FakeAsyncClient)

    test_response = client.post("/api/admin/alerts/test")
    assert test_response.status_code == 200
    assert test_response.json() == {"status": "sent"}
