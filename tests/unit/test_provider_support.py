import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin.crypto import CryptoService
from app.admin.key_repository import KeyRepository
from app.admin.provider_config_repository import ProviderConfigRepository
from app.admin.runtime import set_admin_runtime
from app.admin.settings_repository import SettingsRepository
from app.api import routes_admin
from app.api.routes_admin import (
    _provider_options_support,
    _provider_price_support,
    router,
)
from app.config import settings
from app.providers.base import BaseOptionsProvider, BasePriceProvider
from app.providers.registry import ProviderRegistry


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "ADMIN_AUTH_ENABLED", False)
    db_path = str(tmp_path / "keys.db")
    set_admin_runtime(
        key_repository=KeyRepository(
            db_path, CryptoService("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
        ),
        provider_config_repository=ProviderConfigRepository(db_path),
        settings_repository=SettingsRepository(db_path),
    )

    async def noop_reload(*args):
        return None

    monkeypatch.setattr("app.api.routes_admin.registry.reload_from_config", noop_reload)
    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    set_admin_runtime()


class FakePriceProvider(BasePriceProvider):
    name = "fake"
    price_sec_types = frozenset({"stock", "etf", "index"})

    async def get_historical_prices(self, *args, **kwargs):
        raise NotImplementedError

    async def get_last_price(self, *args, **kwargs):
        raise NotImplementedError

    async def test_connection(self):
        return {"success": True}


class FakeOptionsProvider(BaseOptionsProvider):
    name = "fakeopt"
    option_underlying_sec_types = frozenset({"stock", "etf", "index"})

    async def get_option_chain(self, *args, **kwargs):
        raise NotImplementedError

    async def get_option_quote(self, *args, **kwargs):
        raise NotImplementedError

    async def test_connection(self):
        return {"success": True}


class SupportRegistry(ProviderRegistry):
    provider_classes = {"fake": FakePriceProvider, "fakeopt": FakeOptionsProvider}

    def _initialize_providers(self):
        self._providers = {"fake": FakePriceProvider()}


def test_defaults_are_stock_and_etf():
    assert BasePriceProvider.price_sec_types == {"stock", "etf"}
    assert BasePriceProvider.price_history_sec_types == {"stock", "etf"}
    assert BaseOptionsProvider.option_underlying_sec_types == {"stock", "etf"}


def test_admin_price_and_options_support(monkeypatch):
    monkeypatch.setattr(routes_admin, "registry", SupportRegistry())
    assert _provider_price_support("fake") == {
        "price_sec_types": ["etf", "index", "stock"],
        "price_history_sec_types": ["etf", "stock"],
    }
    assert _provider_options_support("fake") is None
    # Not loaded: falls back to the declared class.
    assert _provider_options_support("fakeopt") == {
        "option_underlying_sec_types": ["etf", "index", "stock"]
    }
    assert _provider_price_support("fakeopt") is None
    assert _provider_price_support("missing") is None


def test_admin_providers_endpoint_lists_support_fields(client) -> None:
    providers = client.get("/api/admin/providers").json()
    assert providers
    for provider in providers:
        assert "price_support" in provider
        assert "options_support" in provider
        assert "volatility_support" in provider
    by_name = {provider["name"]: provider for provider in providers}
    for name, provider in by_name.items():
        if "prices" in provider["capabilities"]:
            support = provider["price_support"]
            assert support is not None, name
            assert {"stock", "etf"} <= set(support["price_sec_types"])
        else:
            assert provider["price_support"] is None
