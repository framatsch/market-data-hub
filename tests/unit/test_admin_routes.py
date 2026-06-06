from types import SimpleNamespace
import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin.crypto import CryptoService
from app.admin.key_repository import KeyRepository
from app.admin.provider_config_repository import ProviderConfigRepository
from app.admin.settings_repository import SettingsRepository
from app.admin.runtime import set_admin_runtime
from app.api.routes_admin import router
from app.config import settings
from app.providers.base import BaseNewsProvider, BaseOptionsProvider, BasePriceProvider
from app.providers.schwab import SchwabProvider


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "ADMIN_AUTH_ENABLED", False)
    key = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    db_path = str(tmp_path / "keys.db")
    key_repo = KeyRepository(db_path, CryptoService(key))
    config_repo = ProviderConfigRepository(db_path)
    settings_repo = SettingsRepository(db_path)
    set_admin_runtime(key_repository=key_repo, provider_config_repository=config_repo, settings_repository=settings_repo)

    async def noop_reload(*args):
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


def test_admin_settings_defaults_get_and_update(client, monkeypatch) -> None:
    registry = __import__("app.api.routes_admin", fromlist=["registry"]).registry
    monkeypatch.setattr(registry, "default_price_provider", "ibkr")
    monkeypatch.setattr(registry, "default_company_provider", "ibkr")
    monkeypatch.setattr(registry, "default_options_provider", "ibkr")
    monkeypatch.setattr(registry, "default_news_provider", "finnhub")

    response = client.get("/api/admin/settings/defaults")

    assert response.status_code == 200
    assert response.json()["default_news_provider"] == "finnhub"

    async def fake_reload(config_repo, settings_repo):
        assert await settings_repo.get("default_price_provider") == "lseg"
        registry.default_price_provider = "lseg"

    monkeypatch.setattr(registry, "reload_from_config", fake_reload)

    update = client.put("/api/admin/settings/defaults", json={"default_price_provider": "LSEG"})

    assert update.status_code == 200
    assert update.json()["default_price_provider"] == "lseg"


def test_admin_settings_capabilities(client, monkeypatch) -> None:
    class PriceProvider(BasePriceProvider):
        async def get_historical_prices(self, symbol, interval, start, end, sec_type="stock"):
            raise NotImplementedError

        async def get_last_price(self, symbol, market_data_type=None, sec_type="stock"):
            raise NotImplementedError

        async def test_connection(self):
            return {"status_code": 200, "success": True, "message": "ok", "details": {}}

    class OptionsProvider(PriceProvider, BaseOptionsProvider):
        async def get_option_chain(self, symbol, expiry, min_strike=None, max_strike=None, right=None, market_data_type=None):
            raise NotImplementedError

        async def get_option_quote(self, symbol, option_id, market_data_type=None):
            raise NotImplementedError

    class NewsProvider(BaseNewsProvider):
        async def get_company_news(self, symbol, from_date, to_date, limit=20, offset=0, language="en", category=None):
            raise NotImplementedError

        async def test_connection(self):
            return {"status_code": 200, "success": True, "message": "ok", "details": {}}

    registry = __import__("app.api.routes_admin", fromlist=["registry"]).registry
    original = registry._providers.copy()
    monkeypatch.setattr(registry, "_providers", {"ibkr": OptionsProvider(), "finnhub": NewsProvider()})

    try:
        response = client.get("/api/admin/settings/capabilities")
    finally:
        registry._providers = original

    assert response.status_code == 200
    assert response.json() == {
        "prices": ["ibkr"],
        "options": ["ibkr"],
        "companies": [],
        "news": ["finnhub"],
    }


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
    monkeypatch.setattr(
        "app.utils.webhooks.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))],
    )
    response = client.put(
        "/api/admin/alerts/webhook",
        json={"webhook_url": "https://hooks.example/test", "format": "slack"},
    )
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


def test_alert_webhook_discord_format(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.utils.webhooks.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))],
    )
    response = client.put(
        "/api/admin/alerts/webhook",
        json={"webhook_url": "https://hooks.example/discord-test", "format": "discord"},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "configured", "format": "discord"}

    class FakeDiscordAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json):
            assert url == "https://hooks.example/discord-test"
            assert "content" in json
            assert json["content"] == "Market Data Hub test alert"
            return SimpleNamespace(status_code=200)

    monkeypatch.setattr("app.api.routes_admin.httpx.AsyncClient", FakeDiscordAsyncClient)

    test_response = client.post("/api/admin/alerts/test")
    assert test_response.status_code == 200
    assert test_response.json() == {"status": "sent"}


def test_alert_webhook_rejects_non_https_url(client) -> None:
    response = client.put("/api/admin/alerts/webhook", json={"webhook_url": "http://hooks.example/test"})

    assert response.status_code == 422
    assert response.json()["detail"] == "webhook_url must use https://"


def test_alert_webhook_rejects_private_resolved_address(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.utils.webhooks.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("10.0.0.5", 443))],
    )

    response = client.put("/api/admin/alerts/webhook", json={"webhook_url": "https://hooks.example/test"})

    assert response.status_code == 422
    assert response.json()["detail"] == "webhook_url must resolve to a public internet address"


def test_alert_webhook_rejects_loopback_literal(client) -> None:
    response = client.put("/api/admin/alerts/webhook", json={"webhook_url": "https://127.0.0.1/test"})

    assert response.status_code == 422
    assert response.json()["detail"] == "webhook_url must resolve to a public internet address"


def test_admin_test_connection_success(client, monkeypatch) -> None:
    class FakeProvider:
        async def test_connection(self):
            return {
                "status_code": 200,
                "success": True,
                "message": "Connected to IBKR",
                "details": {"host": "127.0.0.1", "port": 4001},
            }

    registry = __import__("app.api.routes_admin", fromlist=["registry"]).registry
    monkeypatch.setattr(registry, "get_provider_instance", lambda _: FakeProvider())

    response = client.post("/api/admin/test-connection/ibkr")

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["status_code"] == 200


def test_admin_test_connection_invalid_provider_returns_404(client) -> None:
    response = client.post("/api/admin/test-connection/not-a-provider")

    assert response.status_code == 404
    assert response.json()["detail"] == "Provider not found"


def test_admin_test_connection_requires_auth_when_enabled(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "ADMIN_AUTH_ENABLED", True)

    response = client.post("/api/admin/test-connection/ibkr")

    assert response.status_code == 401


def test_admin_test_connection_timeout_returns_503_payload(client, monkeypatch) -> None:
    class SlowProvider:
        async def test_connection(self):
            await asyncio.sleep(11)
            return {
                "status_code": 200,
                "success": True,
                "message": "late",
                "details": {},
            }

    registry = __import__("app.api.routes_admin", fromlist=["registry"]).registry
    monkeypatch.setattr(registry, "get_provider_instance", lambda _: SlowProvider())

    response = client.post("/api/admin/test-connection/ibkr")

    assert response.status_code == 200
    body = response.json()
    assert body["status_code"] == 503
    assert body["success"] is False
    assert body["message"] == "Connection test timeout"


def test_list_admin_providers(client) -> None:
    response = client.get("/api/admin/providers")
    assert response.status_code == 200
    providers = response.json()
    assert len(providers) > 0
    for p in providers:
        assert "name" in p
        assert "enabled" in p
        assert "status" in p
        assert "config" in p
        assert "config_summary" in p
        assert "timeout_seconds" in p["config_summary"]
        assert "retry_count" in p["config_summary"]
        assert "rate_limit_per_sec" in p["config_summary"]
