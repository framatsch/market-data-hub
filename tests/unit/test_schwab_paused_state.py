from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from app.admin.runtime import set_admin_runtime
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
        key_repository=cast(
            Any,
            FakeKeyRepository(
                {
                    ("schwab", "api_key"): "repo-key",
                    ("schwab", "app_secret"): "repo-secret",
                    ("schwab", "token_json"): '{"access_token": "token"}',
                }
            ),
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
    assert Path(captured["token_path"]).stat().st_mode & 0o777 == 0o600

    await provider.close()
    assert not Path(captured["token_path"]).exists()


async def test_temp_token_removed_when_easy_client_fails(monkeypatch) -> None:
    set_admin_runtime(
        key_repository=cast(
            Any,
            FakeKeyRepository(
                {
                    ("schwab", "api_key"): "repo-key",
                    ("schwab", "app_secret"): "repo-secret",
                    ("schwab", "token_json"): '{"access_token": "token"}',
                }
            ),
        )
    )

    def fake_easy_client(**kwargs):
        assert Path(kwargs["token_path"]).exists()
        raise RuntimeError("expired")

    monkeypatch.setattr(schwab_module, "easy_client", fake_easy_client)
    provider = SchwabProvider()

    with pytest.raises(ProviderConnectionError):
        await provider._get_client()

    assert provider._temp_token_path is None


async def test_unauthorized_with_initialized_client_pauses_and_fires_webhook(monkeypatch) -> None:
    provider = SchwabProvider()
    provider._client = object()
    provider._fire_webhook = AsyncMock()

    with pytest.raises(ProviderConnectionError):
        await provider._handle_error_status(401, "AAPL", "quote")

    assert provider._paused is True
    assert provider._client is None
    provider._fire_webhook.assert_awaited_once()


async def test_unauthorized_without_initialized_client_does_not_pause() -> None:
    provider = SchwabProvider()
    provider._client = None
    provider._fire_webhook = AsyncMock()

    with pytest.raises(ProviderConnectionError):
        await provider._handle_error_status(401, "AAPL", "quote")

    assert provider._paused is False
    assert provider._client is None
    provider._fire_webhook.assert_not_called()


async def test_unpause_clears_paused_state_and_client() -> None:
    provider = SchwabProvider()
    provider._paused = True
    provider._client = object()

    provider.unpause()

    assert provider._paused is False
    assert provider._client is None


async def test_fire_webhook_uses_configured_url(monkeypatch) -> None:
    set_admin_runtime(
        key_repository=cast(
            Any,
            FakeKeyRepository({("schwab", "alert_webhook_url"): "https://hooks.example/test"}),
        )
    )
    monkeypatch.setattr(
        "app.utils.webhooks.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))],
    )
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


async def test_fire_webhook_skips_non_https_url(monkeypatch) -> None:
    set_admin_runtime(
        key_repository=cast(
            Any,
            FakeKeyRepository({("schwab", "alert_webhook_url"): "http://hooks.example/test"}),
        )
    )

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("HTTP client should not be created")

    monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)

    await SchwabProvider()._fire_webhook("message")


async def test_fire_webhook_skips_private_resolved_address(monkeypatch) -> None:
    set_admin_runtime(
        key_repository=cast(
            Any,
            FakeKeyRepository({("schwab", "alert_webhook_url"): "https://hooks.example/test"}),
        )
    )
    monkeypatch.setattr(
        "app.utils.webhooks.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("172.16.0.10", 443))],
    )

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("HTTP client should not be created")

    monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)

    await SchwabProvider()._fire_webhook("message")
