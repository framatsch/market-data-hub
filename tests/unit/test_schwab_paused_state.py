from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from app.admin.runtime import set_admin_runtime
from app.config import settings
from app.providers import schwab as schwab_module
from app.providers.schwab import SchwabProvider
from app.utils.errors import ProviderConnectionError


class FakeKeyRepository:
    def __init__(self, values: dict[tuple[str, str], str | None]) -> None:
        self.values = values

    async def get(self, provider_name: str, credential_name: str) -> str | None:
        return self.values.get((provider_name, credential_name))


@pytest.fixture(autouse=True)
def reset_runtime():
    set_admin_runtime()
    yield
    set_admin_runtime()


async def test_paused_provider_raises_before_client_init(monkeypatch) -> None:
    provider = SchwabProvider()
    provider._paused = True
    monkeypatch.setattr(schwab_module, "easy_client", lambda **kwargs: object())

    with pytest.raises(ProviderConnectionError, match="paused"):
        await provider._get_client()


async def test_token_loaded_from_key_repository(monkeypatch, tmp_path) -> None:
    set_admin_runtime(
        key_repository=FakeKeyRepository(
            {
                ("schwab", "api_key"): "repo-key",
                ("schwab", "app_secret"): "repo-secret",
                ("schwab", "token_json"): '{"access_token": "token"}',
            }
        )
    )
    captured = {}

    def fake_easy_client(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(schwab_module, "easy_client", fake_easy_client)
    provider = SchwabProvider()

    await provider._get_client()

    assert captured["api_key"] == "repo-key"
    assert captured["app_secret"] == "repo-secret"
    assert Path(captured["token_path"]).read_text() == '{"access_token": "token"}'


async def test_unauthorized_with_initialized_client_pauses_and_fires_webhook(monkeypatch) -> None:
    provider = SchwabProvider()
    provider._client = object()
    provider._fire_webhook = AsyncMock()

    with pytest.raises(ProviderConnectionError):
        provider._handle_error_status(401, "AAPL", "quote")

    assert provider._paused is True
    assert provider._client is None
    provider._fire_webhook.assert_called_once()


async def test_unpause_clears_paused_state_and_client() -> None:
    provider = SchwabProvider()
    provider._paused = True
    provider._client = object()

    provider.unpause()

    assert provider._paused is False
    assert provider._client is None


async def test_fire_webhook_uses_configured_url(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SCHWAB_ALERT_WEBHOOK_URL", SecretStr("https://hooks.example/test"))
    sent = {}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json):
            sent["url"] = url
            sent["json"] = json
            return SimpleNamespace(raise_for_status=lambda: None)

    monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)

    await SchwabProvider()._fire_webhook("message")

    assert sent == {"url": "https://hooks.example/test", "json": {"text": "message"}}
