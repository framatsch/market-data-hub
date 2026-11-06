import fnmatch
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi_cache import FastAPICache

from app import cache as response_cache
from app.models.volatility import (
    ImpliedVolatilityTenor,
    VolatilityHistory,
    VolatilityPoint,
    VolatilitySnapshot,
)
from app.providers.base import BaseVolatilityProvider
from app.providers.registry import ProviderRegistry
from app.services.volatility_service import VolatilityService


class FakeRedis:
    """Redis-shaped, byte-preserving fake with failure injection and command tracking."""

    def __init__(self):
        self.entries = {}
        self.ttls = {}
        self.fail = False
        self.calls = 0
        self.unlinked = []
        self.close = AsyncMock()
        self.connection_pool = type("Pool", (), {"disconnect": AsyncMock()})()

    def check(self):
        self.calls += 1
        if self.fail:
            raise ConnectionError("offline (credentials must not be logged)")

    async def ping(self):
        self.check()
        return True

    def pipeline(self, **kwargs):
        redis = self

        class Pipeline:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def ttl(self, key):
                self.key = key
                return self

            def get(self, key):
                return self

            async def execute(self):
                redis.check()
                return redis.ttls.get(self.key, -2), redis.entries.get(self.key)

        return Pipeline()

    async def set(self, key, value, ex):
        self.check()
        self.entries[key] = value
        self.ttls[key] = ex

    async def info(self, section):
        self.check()
        assert section == "memory"
        return {"used_memory": 1024, "maxmemory": 268435456}

    async def scan_iter(self, match, count):
        self.check()
        assert count == 500
        for key in list(self.entries):
            if fnmatch.fnmatch(key, match):
                yield key.encode()

    async def unlink(self, *keys):
        self.check()
        deleted = 0
        for key in keys:
            text = key.decode() if isinstance(key, bytes) else key
            self.unlinked.append(text)
            if text in self.entries:
                self.entries.pop(text)
                self.ttls.pop(text, None)
                deleted += 1
        return deleted


@pytest.fixture
def cache_redis(monkeypatch):
    redis = FakeRedis()
    backend = response_cache.FailOpenRedisBackend(redis)
    monkeypatch.setattr(response_cache, "_backend", backend)
    monkeypatch.setattr(response_cache, "policy", response_cache.CachePolicy())
    FastAPICache.reset()
    FastAPICache.init(
        backend,
        prefix="mdh",
        coder=response_cache.MdhJsonCoder,
        key_builder=response_cache.mdh_key_builder,
    )
    yield redis
    response_cache._disable_cache()


@pytest.fixture
def volatility_env(monkeypatch):
    monkeypatch.setattr(ProviderRegistry, "_initialize_providers", lambda self: None)
    registry = ProviderRegistry()
    providers = {}
    for name in ("lseg", "ibkr"):
        provider = Mock(spec=BaseVolatilityProvider)
        provider.name = name
        provider.volatility_sec_types = frozenset({"stock", "etf", "index", "future"})
        provider.volatility_history_sec_types = (
            provider.volatility_sec_types if name == "lseg" else frozenset({"stock", "etf", "index"})
        )
        provider.volatility_tenors = frozenset({30, 60, 90} if name == "lseg" else {30})
        instrument = "AAPLATMIV.U" if name == "lseg" else "AAPL"
        snapshot = VolatilitySnapshot(
            symbol="AAPL", sec_type="stock", method="provider_atm_index" if name == "lseg" else "provider_model_30d",
            source_instrument=instrument, underlying="AAPL", underlying_name="APPLE INC",
            market="OPRA" if name == "lseg" else "NASDAQ", as_of=date.today(),
            implied=[ImpliedVolatilityTenor(tenor_days=30, iv="0.26765")], provider=name,
        )
        history = VolatilityHistory(
            symbol="AAPL", sec_type="stock", source_instrument=instrument, tenor_days=30, provider=name,
            points=[VolatilityPoint(date=date.today() - timedelta(days=25 - index), iv="0.2") for index in range(25)],
        )
        provider.get_implied_volatility = AsyncMock(return_value=snapshot)
        provider.get_implied_volatility_history = AsyncMock(return_value=history)
        providers[name] = provider
    registry._providers = {**providers, "schwab": object()}
    registry.default_volatility_provider = "lseg"
    return SimpleNamespace(registry=registry, service=VolatilityService(registry), **providers)
