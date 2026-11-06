import asyncio

import pytest

from app.admin.provider_config_repository import ProviderConfigRepository
from app.admin.settings_repository import SettingsRepository
from app.api.routes_admin import _provider_capabilities, _provider_volatility_support
from app.providers.base import BaseVolatilityProvider
from app.providers.registry import ProviderRegistry
from app.utils.errors import AppError, InvalidProviderError


class FakeVolatilityProvider(BaseVolatilityProvider):
    name = "lseg"
    volatility_sec_types = frozenset({"stock", "etf", "index", "future"})
    volatility_history_sec_types = volatility_sec_types
    volatility_tenors = frozenset({30, 60, 90})

    def __init__(self):
        self.closed = False

    async def get_implied_volatility(self, *args, **kwargs):
        raise NotImplementedError

    async def get_implied_volatility_history(self, *args, **kwargs):
        raise NotImplementedError

    async def test_connection(self):
        return {"success": True}

    async def close(self):
        self.closed = True


class VolatilityRegistry(ProviderRegistry):
    provider_classes = {"lseg": FakeVolatilityProvider}

    def _initialize_providers(self):
        self._providers = {"lseg": FakeVolatilityProvider()}


def test_volatility_default_resolution_and_invalid_provider():
    registry = VolatilityRegistry()
    assert registry.default_volatility_provider is None
    with pytest.raises(AppError) as error:
        registry.get_volatility_provider()
    assert error.value.code == "PROVIDER_NOT_AVAILABLE"
    registry._apply_default_settings({"default_volatility_provider": "lseg"})
    assert registry.get_volatility_provider() is registry._providers["lseg"]
    registry._providers["wrong"] = object()
    for name in ("wrong", "missing"):
        registry._apply_default_settings({"default_volatility_provider": name})
        assert registry.default_volatility_provider is None
        with pytest.raises(InvalidProviderError):
            registry.get_volatility_provider(name)


async def test_volatility_default_reload_and_lease(tmp_path):
    config = ProviderConfigRepository(str(tmp_path / "keys.db"))
    settings = SettingsRepository(str(tmp_path / "keys.db"))
    await config.save("lseg", {"enabled": True})
    await settings.set("default_volatility_provider", "lseg")
    registry = VolatilityRegistry()
    await registry.reload_from_config(config, settings)
    provider = registry.get_volatility_provider()
    async with registry.use_volatility_provider() as leased:
        assert leased is provider
        await config.save("lseg", {"enabled": False})
        reload_task = asyncio.create_task(registry.reload_from_config(config, settings))
        await asyncio.sleep(0.01)
        assert not provider.closed
    await reload_task
    assert provider.closed
    assert registry.default_volatility_provider is None


async def test_volatility_lease_rejects_missing_default():
    registry = VolatilityRegistry()
    with pytest.raises(AppError) as error:
        async with registry.use_volatility_provider():
            pytest.fail("No default provider should be leased")
    assert error.value.code == "PROVIDER_NOT_AVAILABLE"
    with pytest.raises(InvalidProviderError):
        async with registry.use_volatility_provider("missing"):
            pytest.fail("Missing provider should not be leased")


def test_admin_volatility_capabilities_and_support(monkeypatch):
    from app.api import routes_admin

    registry = VolatilityRegistry()
    monkeypatch.setattr(routes_admin, "registry", registry)
    assert "volatility" in _provider_capabilities("lseg", registry._providers["lseg"])
    assert "volatility" in _provider_capabilities("lseg", None)
    support = _provider_volatility_support("lseg")
    assert support == {
        "volatility_sec_types": ["etf", "future", "index", "stock"],
        "volatility_history_sec_types": ["etf", "future", "index", "stock"],
        "volatility_tenors": [30, 60, 90],
    }
    registry._providers.clear()
    assert _provider_volatility_support("lseg") == support
    assert _provider_volatility_support("schwab") is None
