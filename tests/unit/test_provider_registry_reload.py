from app.admin.provider_config_repository import ProviderConfigRepository
from app.providers.base import BasePriceProvider
from app.providers.registry import ProviderRegistry


class FakePriceProvider(BasePriceProvider):
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True

    async def get_last_price(self, symbol: str):
        raise NotImplementedError

    async def get_historical_prices(self, symbol: str, interval: str, start, end, sec_type: str = "stock"):
        raise NotImplementedError

    async def get_market_status(self):
        raise NotImplementedError


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
    provider = registry._providers["ibkr"]

    await registry.reload_from_config(repo)

    assert provider.closed is True
    assert "ibkr" not in registry._providers


async def test_registry_reload_applies_runtime_config(tmp_path) -> None:
    repo = ProviderConfigRepository(str(tmp_path / "keys.db"))
    await repo.save("ibkr", {"enabled": True, "timeout_seconds": 22, "retry_count": 6})
    registry = TestRegistry()

    await registry.reload_from_config(repo)

    provider = registry._providers["ibkr"]
    assert provider.timeout_seconds == 22
    assert provider.retry_count == 6
