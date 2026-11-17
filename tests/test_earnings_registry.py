from unittest.mock import AsyncMock

import pytest

from app.admin.settings_repository import SettingsRepository
from app.main import app_error_handler
from app.providers.base import BaseEarningsProvider
from app.providers.registry import ProviderRegistry
from app.utils.errors import AppError, InvalidProviderError, ProviderQuotaExhaustedError


class FakeEarnings(BaseEarningsProvider):
    name = "earnings_fake"

    async def get_upcoming_earnings(self, start, end, roots):
        return []

    async def get_earnings_history(self, root):
        return []

    async def test_connection(self):
        return {"success": True}


@pytest.fixture
def reg(monkeypatch):
    monkeypatch.setattr(ProviderRegistry, "_initialize_providers", lambda self: None)
    value = ProviderRegistry()
    value._providers = {"earnings_fake": FakeEarnings(), "other": object()}
    return value


def test_default_resolution_and_capability(reg, caplog):
    reg._apply_default_settings({"default_earnings_provider": "earnings_fake"})
    assert reg.get_earnings_provider().name == "earnings_fake"
    assert reg.list_available_providers()["earnings"] == ["earnings_fake"]
    reg._apply_default_settings({"default_earnings_provider": "other"})
    assert reg.default_earnings_provider is None
    assert "BaseEarningsProvider" in caplog.text
    with pytest.raises(InvalidProviderError):
        reg.get_earnings_provider("other")


async def test_fresh_install_503(reg):
    reg._apply_default_settings()
    with pytest.raises(AppError) as error:
        async with reg.use_earnings_provider():
            pass
    assert error.value.message == "No earnings provider configured — enable a provider in the admin UI"
    assert (await app_error_handler(None, error.value)).status_code == 503


async def test_provider_lease_released(reg):
    async with reg.use_earnings_provider("earnings_fake") as provider:
        assert reg._provider_inflight[id(provider)] == 1
    assert not reg._provider_inflight
    with pytest.raises(InvalidProviderError):
        async with reg.use_earnings_provider("other"):
            pass


async def test_setting_reload(reg, tmp_path):
    repository = SettingsRepository(str(tmp_path / "settings.db"))
    await repository.set("default_earnings_provider", "earnings_fake")
    config_repo = AsyncMock()
    config_repo.list_all.return_value = []
    reg._apply_default_settings(await repository.get_all())
    assert reg.default_earnings_provider == "earnings_fake"
    await repository.set("default_earnings_provider", None)
    reg._apply_default_settings(await repository.get_all())
    assert reg.default_earnings_provider is None


async def test_quota_error_http_mapping():
    error = ProviderQuotaExhaustedError("alphavantage", "day", 25)
    response = await app_error_handler(None, error)
    assert response.status_code == 429
    assert b'"period":"day"' in response.body
