import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin.crypto import CryptoService
from app.admin.key_repository import KeyRepository
from app.admin.provider_config_repository import ProviderConfigRepository
from app.admin.runtime import get_provider_config_repository, set_admin_runtime
from app.admin.settings_repository import SettingsRepository
from app.api.routes_admin import router
from app.config import settings
from app.main import app as main_app
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
    from app.api import routes_admin as routes_admin_module

    routes_admin_module._credential_reveal_calls.clear()

    async def noop_reload(*args):
        return None

    monkeypatch.setattr("app.api.routes_admin.registry.reload_from_config", noop_reload)
    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    set_admin_runtime()
    routes_admin_module._credential_reveal_calls.clear()


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
    assert "value" not in slot


@pytest.mark.parametrize("provider", ["alphavantage", "financialdatasets"])
@pytest.mark.parametrize("budget", ["request_budget_per_day", "request_budget_per_month"])
def test_metered_budget_settings_validate(client, provider, budget):
    path = f"/api/admin/providers/{provider}/config"
    response = client.put(path, json={"connection_config": {budget: -1}})
    assert response.status_code == 422
    assert "non-negative integer" in response.json()["detail"]
    response = client.put(path, json={"connection_config": {budget: 0}})
    assert response.status_code == 200
    assert response.json()["connection_config"][budget] == 0


def test_metered_provider_usage_and_defaults(client, monkeypatch):
    from app.providers import request_budget

    request_budget._local.clear()
    monkeypatch.setattr(request_budget, "budget_redis", lambda: None)
    response = client.get("/api/admin/providers/alphavantage/usage")
    assert response.status_code == 200
    assert response.json()["day"]["budget"] == 25
    assert response.json()["shared"] is False
    response = client.get("/api/admin/providers/financialdatasets/usage")
    assert response.json()["month"]["budget"] == 1000
    assert client.get("/api/admin/providers/ibkr/usage").status_code == 404


def test_metered_usage_requires_auth(client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_AUTH_ENABLED", True)
    assert client.get("/api/admin/providers/alphavantage/usage").status_code == 401


def test_reveal_admin_credential_returns_plaintext_value(client) -> None:
    response = client.post(
        "/api/admin/keys",
        json={"provider_name": "finnhub", "credential_name": "api_key", "value": "secret-key"},
    )
    assert response.status_code == 200

    revealed = client.get("/api/admin/credentials/finnhub/api_key/reveal")

    assert revealed.status_code == 200
    assert revealed.json() == {
        "provider": "finnhub",
        "credential_name": "api_key",
        "value": "secret-key",
        "set": True,
    }


def test_reveal_admin_credential_returns_set_false_when_missing(client) -> None:
    revealed = client.get("/api/admin/credentials/finnhub/api_key/reveal")

    assert revealed.status_code == 200
    assert revealed.json() == {
        "provider": "finnhub",
        "credential_name": "api_key",
        "value": None,
        "set": False,
    }


def test_reveal_admin_credential_rejects_unknown_provider(client) -> None:
    revealed = client.get("/api/admin/credentials/not-a-provider/api_key/reveal")

    assert revealed.status_code == 400
    assert revealed.json()["detail"] == "Unknown provider: not-a-provider"


def test_reveal_admin_credential_rejects_unknown_credential(client) -> None:
    revealed = client.get("/api/admin/credentials/finnhub/not-a-credential/reveal")

    assert revealed.status_code == 400
    assert (
        revealed.json()["detail"]
        == "Unknown credential: not-a-credential for provider finnhub"
    )


def test_reveal_admin_credential_rate_limit(client) -> None:
    client.post(
        "/api/admin/keys",
        json={"provider_name": "finnhub", "credential_name": "api_key", "value": "secret-key"},
    )

    for _ in range(10):
        response = client.get("/api/admin/credentials/finnhub/api_key/reveal")
        assert response.status_code == 200

    limited = client.get("/api/admin/credentials/finnhub/api_key/reveal")
    assert limited.status_code == 429
    assert limited.json()["detail"] == "Credential reveal rate limit exceeded"


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
    cc = gateway.json()["connection_config"]
    assert cc["host"] == "192.168.1.10"
    assert cc["port"] == 4001


@pytest.mark.parametrize("key", ["request_budget_per_day", "request_budget_per_month"])
@pytest.mark.parametrize("value", [-1, 1.5, True, "25"])
def test_metered_budget_validation(client, key, value):
    response = client.put("/api/admin/providers/alphavantage/config", json={
        "connection_config": {key: value},
    })
    assert response.status_code == 422


def test_metered_budget_defaults_usage_and_credentials(client):
    for provider, day, month in (("alphavantage", 25, 0), ("financialdatasets", 0, 1000)):
        config = client.get(f"/api/admin/providers/{provider}/config").json()
        assert config["enabled"] is False
        assert config["connection_config"] == {"request_budget_per_day": day, "request_budget_per_month": month}
        usage = client.get(f"/api/admin/providers/{provider}/usage")
        assert usage.status_code == 200
        assert usage.json()["day"]["budget"] == day
        assert usage.json()["month"]["budget"] == month
        assert "resets_at" in usage.json()["day"]
        saved = client.put(f"/api/admin/credentials/{provider}", json={"api_key": "fixture-key"})
        assert saved.status_code == 200
    assert client.get("/api/admin/providers/ibkr/usage").status_code == 404


def test_metered_usage_requires_admin_auth(client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_AUTH_ENABLED", True)
    assert client.get("/api/admin/providers/alphavantage/usage").status_code == 401


def test_provider_config_validation(client) -> None:
    response = client.put("/api/admin/providers/schwab/config", json={"timeout_seconds": -1})

    assert response.status_code == 422


def test_admin_settings_defaults_get_and_update(client, monkeypatch) -> None:
    registry = __import__("app.api.routes_admin", fromlist=["registry"]).registry
    monkeypatch.setattr(registry, "default_price_provider", None)
    monkeypatch.setattr(registry, "default_company_provider", None)
    monkeypatch.setattr(registry, "default_options_provider", None)
    monkeypatch.setattr(registry, "default_news_provider", None)
    monkeypatch.setattr(registry, "default_volatility_provider", None)
    monkeypatch.setattr(registry, "default_earnings_provider", None)

    response = client.get("/api/admin/settings/defaults")

    assert response.status_code == 200
    assert response.json() == {
        "default_price_provider": "",
        "default_company_provider": "",
        "default_options_provider": "",
        "default_news_provider": "",
        "default_volatility_provider": "",
        "default_earnings_provider": "",
        "default_earnings_upcoming_provider": "",
        "default_earnings_history_provider": "",
    }

    async def fake_reload(config_repo, settings_repo):
        assert await settings_repo.get("default_price_provider") == "lseg"
        registry.default_price_provider = "lseg"

    monkeypatch.setattr(registry, "reload_from_config", fake_reload)

    update = client.put("/api/admin/settings/defaults", json={"default_price_provider": "LSEG"})

    assert update.status_code == 200
    assert update.json()["default_price_provider"] == "lseg"


def test_admin_settings_capabilities(client) -> None:
    config_repo = get_provider_config_repository()
    asyncio.run(config_repo.save("ibkr", {"enabled": True}))
    asyncio.run(config_repo.save("lseg", {"enabled": True}))
    asyncio.run(config_repo.save("finnhub", {"enabled": True}))
    asyncio.run(config_repo.save("schwab", {"enabled": False}))
    asyncio.run(config_repo.save("mock", {"enabled": False}))
    asyncio.run(config_repo.save("polygon", {"enabled": False}))
    asyncio.run(config_repo.save("prixe", {"enabled": False}))

    response = client.get("/api/admin/settings/capabilities")

    assert response.status_code == 200
    assert response.json() == {
        "prices": ["ibkr", "lseg"],
        "options": ["ibkr"],
        "companies": ["ibkr", "lseg"],
        "news": ["finnhub"],
        "volatility": ["ibkr", "lseg"],
        "earnings_upcoming": [],
        "earnings_history": [],
        "earnings": [],
    }


def test_admin_earnings_capability_and_default(client, monkeypatch) -> None:
    config_repo = get_provider_config_repository()
    asyncio.run(config_repo.save("alphavantage", {"enabled": True}))
    asyncio.run(config_repo.save("financialdatasets", {"enabled": True}))
    capabilities = client.get("/api/admin/settings/capabilities").json()
    assert capabilities["earnings"] == ["alphavantage", "financialdatasets"]
    assert capabilities["earnings_upcoming"] == ["alphavantage"]
    assert capabilities["earnings_history"] == ["alphavantage", "financialdatasets"]

    from app.api.routes_admin import registry

    async def fake_reload(config_repo, settings_repo):
        registry.default_earnings_upcoming_provider = await settings_repo.get(
            "default_earnings_upcoming_provider"
        )
        registry.default_earnings_history_provider = await settings_repo.get(
            "default_earnings_history_provider"
        )

    monkeypatch.setattr(registry, "default_earnings_provider", None)
    monkeypatch.setattr(registry, "reload_from_config", fake_reload)
    response = client.put(
        "/api/admin/settings/defaults",
        json={"default_earnings_provider": "AlphaVantage"},
    )
    body = response.json()
    assert body["default_earnings_provider"] == "alphavantage"
    assert body["default_earnings_upcoming_provider"] == "alphavantage"
    assert body["default_earnings_history_provider"] == "alphavantage"

    # A history-only provider as shorthand sets only the history role.
    response = client.put(
        "/api/admin/settings/defaults",
        json={"default_earnings_provider": "financialdatasets"},
    )
    body = response.json()
    assert body["default_earnings_upcoming_provider"] == "alphavantage"
    assert body["default_earnings_history_provider"] == "financialdatasets"


def test_admin_volatility_default_round_trip(client, monkeypatch) -> None:
    from app.api.routes_admin import registry

    monkeypatch.setattr(registry, "default_volatility_provider", None)

    async def fake_reload(config_repo, settings_repo):
        registry.default_volatility_provider = await settings_repo.get(
            "default_volatility_provider"
        )

    monkeypatch.setattr(registry, "reload_from_config", fake_reload)
    response = client.put(
        "/api/admin/settings/defaults", json={"default_volatility_provider": "LSEG"}
    )
    assert response.status_code == 200
    assert response.json()["default_volatility_provider"] == "lseg"
    assert client.get("/api/admin/settings/defaults").json()[
        "default_volatility_provider"
    ] == "lseg"


def test_schwab_auth_callback_saves_token_and_unpauses(client, monkeypatch) -> None:
    client.put("/api/admin/credentials/schwab", json={"api_key": "key", "app_secret": "secret"})
    saved = {}

    def fake_client_from_received_url(*args, **kwargs):
        if len(args) >= 1:
            saved["api_key"] = args[0]
        if len(args) >= 2:
            saved["app_secret"] = args[1]
        saved.update(kwargs)
        return SimpleNamespace(token={"access_token": "token"})

    provider = SchwabProvider()
    provider._paused = True
    monkeypatch.setattr("app.api.routes_admin.client_from_received_url", fake_client_from_received_url)
    monkeypatch.setitem(__import__("app.api.routes_admin", fromlist=["registry"]).registry._providers, "schwab", provider)

    from app.api.routes_admin import _schwab_pending_states, _utcnow
    mock_auth_context = SimpleNamespace(state="test_state")
    _schwab_pending_states["test_state"] = (mock_auth_context, _utcnow())

    response = client.post("/api/admin/schwab/auth/callback", json={"received_url": "https://callback?code=abc&state=test_state"})

    print(response.json())
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert saved["received_url"] == "https://callback?code=abc&state=test_state"
    assert provider._paused is False
    status = client.get("/api/admin/schwab/auth/status")
    assert status.json()["storage"] == "sqlite"


def test_schwab_auth_url_returns_503_when_stored_credentials_fail_decryption(
    client, tmp_path
) -> None:
    db_path = str(tmp_path / "keys.db")
    other_key = "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB="
    stale_repo = KeyRepository(db_path, CryptoService(other_key))
    asyncio.run(stale_repo.save("schwab", "api_key", "stale-key"))
    asyncio.run(stale_repo.save("schwab", "app_secret", "stale-secret"))
    asyncio.run(stale_repo.save("schwab", "token_json", '{"access_token": "stale"}'))

    url_response = client.get("/api/admin/schwab/auth/url")
    assert url_response.status_code == 503
    assert url_response.json()["detail"] == "Schwab credentials not configured"

    status_response = client.get("/api/admin/schwab/auth/status")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "not_configured"

    creds_response = client.get("/api/admin/credentials")
    assert creds_response.status_code == 200
    schwab_api_key = next(
        item
        for item in creds_response.json()
        if item["provider"] == "schwab" and item["credential_name"] == "api_key"
    )
    assert schwab_api_key["set"] is False



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


def test_admin_test_connection_propagates_apperror(client, monkeypatch) -> None:
    from app.utils.errors import ProviderConnectionError

    class BrokenProvider:
        async def test_connection(self):
            raise ProviderConnectionError("service unavailable")

    registry = __import__("app.api.routes_admin", fromlist=["registry"]).registry
    monkeypatch.setattr(registry, "get_provider_instance", lambda _: BrokenProvider())

    with pytest.raises(ProviderConnectionError):
        client.post("/api/admin/test-connection/ibkr")


def test_admin_test_connection_propagates_apperror_in_real_app(monkeypatch, tmp_path) -> None:
    from app.utils.errors import ProviderConnectionError

    key = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    db_path = str(tmp_path / "keys.db")
    key_repo = KeyRepository(db_path, CryptoService(key))
    config_repo = ProviderConfigRepository(db_path)
    settings_repo = SettingsRepository(db_path)
    set_admin_runtime(
        key_repository=key_repo,
        provider_config_repository=config_repo,
        settings_repository=settings_repo,
    )

    class BrokenProvider:
        async def test_connection(self):
            raise ProviderConnectionError("service unavailable")

    registry = __import__("app.api.routes_admin", fromlist=["registry"]).registry

    async def noop_reload(*args):
        return None

    monkeypatch.setattr("app.api.routes_admin.registry.reload_from_config", noop_reload)
    monkeypatch.setattr(registry, "get_provider_instance", lambda _: BrokenProvider())
    monkeypatch.setattr(settings, "ADMIN_AUTH_ENABLED", False)

    client = TestClient(main_app, raise_server_exceptions=False)
    response = client.post("/api/admin/test-connection/ibkr")

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "PROVIDER_CONNECTION_ERROR"
    assert body["error"]["message"] == "service unavailable"

    set_admin_runtime()


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


def test_provider_details_state_price_adjustment_and_earnings_capability(client) -> None:
    providers = {item["name"]: item for item in client.get("/api/admin/providers").json()}
    assert providers["alphavantage"]["price_adjustment"] == "none"
    assert providers["financialdatasets"]["price_adjustment"] == "unknown"
    assert providers["ibkr"]["price_adjustment"] is None
    assert providers["alphavantage"]["capabilities"] == ["prices", "earnings_upcoming", "earnings_history"]
    assert providers["financialdatasets"]["capabilities"] == ["prices", "companies", "earnings_history"]
    assert providers["alphavantage"]["price_support"]["native_intervals"] == ["1d", "1w"]
    assert providers["alphavantage"]["enabled"] is False
