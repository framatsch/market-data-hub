from unittest.mock import AsyncMock

import pytest

from app.admin.settings_repository import SettingsRepository
from app.main import app_error_handler
from app.providers.base import BaseEarningsHistoryProvider, BaseEarningsUpcomingProvider
from app.providers.registry import ProviderRegistry
from app.utils.errors import AppError, InvalidProviderError, ProviderQuotaExhaustedError


class FakeEarnings(BaseEarningsUpcomingProvider, BaseEarningsHistoryProvider):
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
    assert "BaseEarningsUpcomingProvider" in caplog.text
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


class HistoryOnlyFake(BaseEarningsHistoryProvider):
    name = "history_fake"

    async def get_earnings_history(self, root):
        return []

    async def test_connection(self):
        return {}


async def test_role_defaults_interface_check_and_catalog(reg):
    reg._providers["history_fake"] = HistoryOnlyFake()
    reg._apply_default_settings({
        "default_earnings_upcoming_provider": "history_fake",  # lacks the interface
        "default_earnings_history_provider": "history_fake",
    })
    assert reg.default_earnings_upcoming_provider is None
    assert reg.default_earnings_history_provider == "history_fake"
    available = reg.list_available_providers()
    assert available["earnings_upcoming"] == ["earnings_fake"]
    assert available["earnings_history"] == ["earnings_fake", "history_fake"]
    assert available["earnings"] == ["earnings_fake", "history_fake"]
    with pytest.raises(AppError) as error:
        reg.get_earnings_provider(role="upcoming")
    assert "earnings upcoming" in error.value.message
    with pytest.raises(InvalidProviderError):
        reg.get_earnings_provider("history_fake", role="upcoming")
    assert reg.get_earnings_provider(role="history").name == "history_fake"


async def test_legacy_default_is_migrated_once(reg, tmp_path):
    repository = SettingsRepository(str(tmp_path / "settings.db"))
    await repository.set("default_earnings_provider", "earnings_fake")
    config_repo = AsyncMock()
    config_repo.list_all.return_value = []
    settings = await repository.get_all()
    await reg._migrate_earnings_default(repository, settings)
    assert await repository.get("default_earnings_upcoming_provider") == "earnings_fake"
    assert await repository.get("default_earnings_history_provider") == "earnings_fake"
    assert await repository.get("default_earnings_provider") is None
    # A second run keeps an explicit role choice untouched.
    await repository.set("default_earnings_provider", "other")
    await repository.set("default_earnings_history_provider", "earnings_fake")
    await reg._migrate_earnings_default(repository, await repository.get_all())
    assert await repository.get("default_earnings_upcoming_provider") == "earnings_fake"
    assert await repository.get("default_earnings_history_provider") == "earnings_fake"


async def test_legacy_history_only_default_migrates_to_history_role(reg, tmp_path):
    reg._providers["history_fake"] = HistoryOnlyFake()
    repository = SettingsRepository(str(tmp_path / "settings.db"))
    await repository.set("default_earnings_provider", "history_fake")
    settings = await repository.get_all()
    await reg._migrate_earnings_default(repository, settings)
    assert await repository.get("default_earnings_history_provider") == "history_fake"
    assert await repository.get("default_earnings_upcoming_provider") is None
    assert await repository.get("default_earnings_provider") is None
    reg._apply_default_settings(settings)
    assert reg.default_earnings_upcoming_provider is None
    assert reg.default_earnings_history_provider == "history_fake"


def test_role_settings_by_interface(reg):
    reg._providers["history_fake"] = HistoryOnlyFake()
    both = ("default_earnings_upcoming_provider", "default_earnings_history_provider")
    assert reg.earnings_role_settings("history_fake") == ("default_earnings_history_provider",)
    assert reg.earnings_role_settings("earnings_fake") == both
    # Not loaded: decided by the provider class.
    assert reg.earnings_role_settings("financialdatasets") == ("default_earnings_history_provider",)
    assert reg.earnings_role_settings("earningsapi") == both
    # Unknown or without earnings interface: both, so the resolution warns as before.
    assert reg.earnings_role_settings("nope") == both
    assert reg.earnings_role_settings("other") == both
