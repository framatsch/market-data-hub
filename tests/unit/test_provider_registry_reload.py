from typing import cast

from app.admin.provider_config_repository import ProviderConfigRepository
from app.admin.settings_repository import SettingsRepository
from app.providers.base import BasePriceProvider
from app.providers.registry import ProviderRegistry


class FakePriceProvider(BasePriceProvider):
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True

    async def get_last_price(self, symbol: str, market_data_type: int | None = None, sec_type: str = "stock"):
        raise NotImplementedError

    async def get_historical_prices(self, symbol: str, interval: str, start, end, sec_type: str = "stock"):
        raise NotImplementedError

    async def get_market_status(self):
        raise NotImplementedError

    async def test_connection(self) -> dict:
        return {"success": True, "status_code": 200, "message": "ok", "details": {}}


class CustomConfigureProvider(FakePriceProvider):
    def configure(self, config) -> None:
        self.configured_timeout = config.timeout_seconds
        self.timeout_seconds = 999


class TestRegistry(ProviderRegistry):
    provider_classes = {"ibkr": FakePriceProvider, "finnhub": FakePriceProvider}

    def _initialize_providers(self):
        self._providers = {"ibkr": FakePriceProvider()}


async def test_registry_reload_enables_provider(tmp_path) -> None:
    repo = ProviderConfigRepository(str(tmp_path / "keys.db"))
    await repo.save("finnhub", {"enabled": True})
    registry = TestRegistry()

    await registry.reload_from_config(repo)

    assert "finnhub" in registry._providers


async def test_registry_reload_disables_provider_and_closes_it(tmp_path) -> None:
    repo = ProviderConfigRepository(str(tmp_path / "keys.db"))
    await repo.save("ibkr", {"enabled": False})
    registry = TestRegistry()
    provider = cast(FakePriceProvider, registry._providers["ibkr"])

    await registry.reload_from_config(repo)

    assert provider.closed is True
    assert "ibkr" not in registry._providers


async def test_registry_reload_applies_runtime_config(tmp_path) -> None:
    repo = ProviderConfigRepository(str(tmp_path / "keys.db"))
    await repo.save("ibkr", {"enabled": True, "timeout_seconds": 22, "retry_count": 6})
    registry = TestRegistry()

    await registry.reload_from_config(repo)

    provider = cast(FakePriceProvider, registry._providers["ibkr"])
    assert getattr(provider, "timeout_seconds") == 22
    assert getattr(provider, "retry_count") == 6


async def test_registry_reload_does_not_override_provider_configure(tmp_path) -> None:
    class CustomRegistry(TestRegistry):
        provider_classes = {"ibkr": CustomConfigureProvider}

        def _initialize_providers(self):
            self._providers = {"ibkr": CustomConfigureProvider()}

    repo = ProviderConfigRepository(str(tmp_path / "keys.db"))
    await repo.save("ibkr", {"enabled": True, "timeout_seconds": 22})
    registry = CustomRegistry()

    await registry.reload_from_config(repo)

    provider = cast(CustomConfigureProvider, registry._providers["ibkr"])
    assert provider.configured_timeout == 22
    assert provider.timeout_seconds == 999


async def test_registry_reload_uses_database_default(tmp_path) -> None:
    repo = ProviderConfigRepository(str(tmp_path / "keys.db"))
    settings_repo = SettingsRepository(str(tmp_path / "keys.db"))
    await repo.save("ibkr", {"enabled": True})
    await repo.save("finnhub", {"enabled": True})
    await settings_repo.set("default_price_provider", "finnhub")
    registry = TestRegistry()

    await registry.reload_from_config(repo, settings_repo)

    assert registry.default_price_provider == "finnhub"


async def test_registry_reload_uses_ibkr_database_default(tmp_path) -> None:
    repo = ProviderConfigRepository(str(tmp_path / "keys.db"))
    settings_repo = SettingsRepository(str(tmp_path / "keys.db"))
    await repo.save("ibkr", {"enabled": True})
    await settings_repo.set("default_price_provider", "ibkr")
    registry = TestRegistry()

    await registry.reload_from_config(repo, settings_repo)

    assert registry.get_price_provider() is registry.get_provider_instance("ibkr")


async def test_registry_reload_returns_none_for_invalid_database_default(tmp_path) -> None:
    repo = ProviderConfigRepository(str(tmp_path / "keys.db"))
    settings_repo = SettingsRepository(str(tmp_path / "keys.db"))
    await repo.save("ibkr", {"enabled": True})
    await settings_repo.set("default_price_provider", "missing")
    registry = TestRegistry()

    await registry.reload_from_config(repo, settings_repo)

    assert registry.default_price_provider is None


async def test_registry_reload_seeds_missing_provider_rows_as_disabled(tmp_path) -> None:
    repo = ProviderConfigRepository(str(tmp_path / "keys.db"))
    settings_repo = SettingsRepository(str(tmp_path / "keys.db"))
    registry = TestRegistry()

    await registry.reload_from_config(repo, settings_repo)

    configs = {config.provider_name: config for config in await repo.list_all()}
    assert all(config.enabled is False for config in configs.values())


async def test_registry_reload_seeds_default_settings_as_none(tmp_path) -> None:
    repo = ProviderConfigRepository(str(tmp_path / "keys.db"))
    settings_repo = SettingsRepository(str(tmp_path / "keys.db"))
    registry = TestRegistry()

    await registry.reload_from_config(repo, settings_repo)

    assert await settings_repo.get("default_price_provider") is None
    assert await settings_repo.get("default_company_provider") is None
    assert await settings_repo.get("default_options_provider") is None
    assert await settings_repo.get("default_news_provider") is None


async def test_registry_reload_seed_is_idempotent_for_existing_defaults(tmp_path) -> None:
    repo = ProviderConfigRepository(str(tmp_path / "keys.db"))
    settings_repo = SettingsRepository(str(tmp_path / "keys.db"))
    registry = TestRegistry()

    await settings_repo.set("default_price_provider", "ibkr")
    await registry.reload_from_config(repo, settings_repo)

    assert await settings_repo.get("default_price_provider") == "ibkr"
