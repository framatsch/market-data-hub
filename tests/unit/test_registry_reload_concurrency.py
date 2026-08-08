import asyncio
from typing import Any

from app.admin.provider_config_repository import ProviderConfigRepository
from app.admin.settings_repository import SettingsRepository
from app.providers.base import BasePriceProvider
from app.providers.registry import ProviderRegistry


class SlowClosePriceProvider(BasePriceProvider):
    def __init__(self) -> None:
        self.close_started = asyncio.Event()
        self.release_close = asyncio.Event()
        self.closed = False

    async def close(self) -> None:
        self.close_started.set()
        await self.release_close.wait()
        self.closed = True

    async def get_last_price(self, symbol: str, market_data_type: int | None = None, sec_type: str = "stock") -> Any:
        raise NotImplementedError

    async def get_historical_prices(self, symbol: str, interval: str, start: Any, end: Any, sec_type: str = "stock") -> list[Any]:
        raise NotImplementedError

    async def get_market_status(self) -> dict[str, Any]:
        raise NotImplementedError

    async def test_connection(self) -> dict[str, Any]:
        return {"success": True, "status_code": 200, "message": "ok", "details": {}}


class NewPriceProvider(SlowClosePriceProvider):
    pass


class ConcurrencyRegistry(ProviderRegistry):
    provider_classes = {"ibkr": NewPriceProvider}

    def _initialize_providers(self) -> None:
        self._providers = {"ibkr": SlowClosePriceProvider()}


async def test_reload_removes_provider_before_awaiting_close(tmp_path) -> None:
    repo = ProviderConfigRepository(str(tmp_path / "keys.db"))
    settings_repo = SettingsRepository(str(tmp_path / "keys.db"))
    await repo.save("ibkr", {"enabled": False})

    registry = ConcurrencyRegistry()
    old_provider = registry.get_provider_instance("ibkr")
    assert old_provider is not None

    reload_task = asyncio.create_task(registry.reload_from_config(repo, settings_repo))
    await old_provider.close_started.wait()  # type: ignore[attr-defined]

    current_provider = registry.get_provider_instance("ibkr")
    assert current_provider is None

    old_provider.release_close.set()  # type: ignore[attr-defined]
    await reload_task
