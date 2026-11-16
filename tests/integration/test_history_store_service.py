"""PriceService and VolatilityService through a real PostgreSQL history store."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app import response_meta
from app.admin.provider_config_repository import ProviderConfigRepository
from app.admin.runtime import set_admin_runtime
from app.models.price import PriceBar
from app.models.volatility import VolatilityHistory, VolatilityPoint
from app.providers.base import BasePriceProvider, BaseVolatilityProvider
from app.providers.registry import ProviderRegistry
from app.services.price_service import PriceService
from app.services.volatility_service import VolatilityService
from app.store import engine
from app.utils.errors import ProviderConnectionError
from app.utils.symbols import parse_symbol

pytestmark = pytest.mark.integration
SAT = datetime(2026, 11, 14, 12, tzinfo=UTC)


def u(*a):
    return datetime(*a, tzinfo=UTC)


class Provider(BasePriceProvider):
    def __init__(self, name, natives, step=1):
        self.name = name
        self.native_intervals = frozenset(natives)
        self.calls = []
        self.error = None

    async def get_last_price(self, *a, **k):
        raise NotImplementedError

    async def test_connection(self):
        return {}

    async def get_historical_prices(self, symbol, interval, start, end, extended_hours=False, sec_type="stock"):
        self.calls.append((interval, start, end))
        if self.error:
            raise self.error
        out = []
        day = date(2026, 10, 1)
        while day <= date(2026, 11, 13):
            stamp = datetime(day.year, day.month, day.day, tzinfo=UTC)
            if day.weekday() < 5 and start <= stamp <= end:
                out.append(PriceBar(symbol=symbol, start=stamp, end=stamp, open=Decimal(100), high=Decimal(101),
                                    low=Decimal(99), close=Decimal(100), volume=10, provider=self.name,
                                    source_instrument=symbol))
            day += timedelta(days=1)
        return out


@pytest.fixture
def env(db, monkeypatch, tmp_path):
    repo = ProviderConfigRepository(str(tmp_path / "k.db"))
    set_admin_runtime(provider_config_repository=repo)
    monkeypatch.setattr(ProviderRegistry, "_initialize_providers", lambda self: None)
    registry = ProviderRegistry()
    ibkr, schwab, polygon = Provider("ibkr", {"1d", "1h"}), Provider("schwab", {"1d"}), Provider("polygon", {"1d"})
    registry._providers = {"ibkr": ibkr, "schwab": schwab, "polygon": polygon}
    registry.default_price_provider = "ibkr"
    yield SimpleNamespace(service=PriceService(registry), repo=repo, ibkr=ibkr, schwab=schwab, polygon=polygon)
    set_admin_runtime()


async def history(service, interval="1d", provider="ibkr", start=u(2026, 10, 1)):
    return await service.get_historical_prices(parse_symbol("AAPL"), interval, start, SAT, provider_name=provider)


async def test_daily_goes_through_store_and_meta_is_set(env):
    token = response_meta.begin()
    try:
        first = await history(env.service)
        await history(env.service)
        meta = response_meta.current()
    finally:
        response_meta.end(token)
    assert len(env.ibkr.calls) == 1 and meta.data_as_of is not None and not meta.stale
    assert {b.provider for b in first} == {"ibkr"}
    # upper-case interval takes the same path
    await history(env.service, "1D")
    assert len(env.ibkr.calls) == 1


async def test_unlisted_interval_and_disabled_store_use_provider(env):
    await history(env.service, "1h")
    await history(env.service, "1h")
    assert len(env.ibkr.calls) == 2
    await env.repo.save("ibkr", {"history_store_intervals": ["1d", "1h"]})
    await history(env.service, "1h")
    await history(env.service, "1h", start=u(2026, 10, 1))
    assert len(env.ibkr.calls) == 3  # one load, then served from the store


async def test_derived_weekly_series_is_stored_marked_and_source_untouched(env):
    await env.repo.save("polygon", {"history_store_intervals": ["1d", "1w"]})
    await history(env.service, "1d", "polygon")
    first = await history(env.service, "1w", "polygon", u(2026, 10, 7))
    assert all(b.source_interval == "1d" for b in first)
    calls = len(env.polygon.calls)
    second = await history(env.service, "1wk", "polygon", u(2026, 10, 7))
    assert len(env.polygon.calls) == calls
    assert [b.start for b in second][:-1] == [b.start for b in first][:-1]
    assert all(b.source_interval == "1d" for b in second)
    async with engine.session_scope() as s:
        rows = (await s.execute(text("select interval, source_interval, count(*) from history_series s left join price_bars b on b.series_id=s.id group by 1,2 order by 1"))).all()
    assert [(r[0], r[1]) for r in rows] == [("1d", None), ("1w", "1d")]


async def test_source_change_reloads_series(env):
    await env.repo.save("polygon", {"history_store_intervals": ["1w"]})
    await history(env.service, "1w", "polygon", u(2026, 10, 7))
    env.polygon.native_intervals = frozenset({"1d", "1w"})
    calls = len(env.polygon.calls)
    bars = await history(env.service, "1w", "polygon", u(2026, 10, 7))
    assert len(env.polygon.calls) > calls
    assert {b.source_interval for b in bars} == {None}


async def test_other_provider_serves_daily_when_requested_one_fails(env):
    await history(env.service, "1d", "schwab")
    env.ibkr.error = ProviderConnectionError("down")
    token = response_meta.begin()
    try:
        bars = await history(env.service, "1d", "ibkr")
        meta = response_meta.current()
    finally:
        response_meta.end(token)
    assert {b.provider for b in bars} == {"schwab"}
    assert meta.stale and meta.source_provider == "schwab"
    assert meta.stale_reason == "PROVIDER_CONNECTION_ERROR"
    async with engine.session_scope() as s:
        count = (await s.execute(text("select count(*) from history_series where provider='ibkr' and covered_from is not null"))).scalar()
    assert count == 0


async def test_other_provider_is_not_used_for_hourly(env):
    await env.repo.save("ibkr", {"history_store_intervals": ["1h"]})
    await env.repo.save("polygon", {"history_store_intervals": ["1h"]})
    env.polygon.native_intervals = frozenset({"1d", "1h"})
    await history(env.service, "1h", "polygon")
    env.ibkr.error = ProviderConnectionError("down")
    with pytest.raises(ProviderConnectionError):
        await history(env.service, "1h", "ibkr")


async def test_database_failure_is_fail_open(env):
    class Broken:
        def __call__(self):
            raise ConnectionRefusedError("db down")

    engine.set_session_factory(Broken())
    bars = await history(env.service)
    assert bars and len(env.ibkr.calls) == 1
    again = await history(env.service)  # cooldown: provider directly, no store retry
    assert again and len(env.ibkr.calls) == 2


class IvProvider(BaseVolatilityProvider):
    name = "lseg"
    volatility_sec_types = frozenset({"stock"})
    volatility_history_sec_types = frozenset({"stock"})
    volatility_tenors = frozenset({30})

    def __init__(self):
        self.calls = 0
        self.error = None

    async def get_implied_volatility(self, *a, **k):
        raise NotImplementedError

    async def test_connection(self):
        return {}

    async def get_implied_volatility_history(self, symbol, start, end, tenor_days=30, sec_type="stock", ric=None):
        self.calls += 1
        if self.error:
            raise self.error
        points = []
        day = date(2026, 1, 1)
        value = 0
        while day <= date(2026, 11, 13):
            if day.weekday() < 5:
                value += 1
                if start <= day <= end:
                    points.append(VolatilityPoint(date=day, iv=Decimal("0.1") + Decimal(value % 50) / 100))
            day += timedelta(days=1)
        return VolatilityHistory(symbol=symbol, sec_type="stock", source_instrument="AAPLATMIV.U",
                                 tenor_days=30, points=points, provider="lseg")


@pytest.fixture
def iv_env(db, monkeypatch):
    monkeypatch.setattr(ProviderRegistry, "_initialize_providers", lambda self: None)
    registry = ProviderRegistry()
    provider = IvProvider()
    registry._providers = {"lseg": provider}
    registry.default_volatility_provider = "lseg"
    return SimpleNamespace(service=VolatilityService(registry), provider=provider)


class FrozenDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 11, 14)


async def test_iv_stats_from_store_equal_provider_only_and_stale(iv_env, monkeypatch):
    monkeypatch.setattr("app.services.volatility_service.date", FrozenDate)
    symbol = parse_symbol("AAPL")
    first = await iv_env.service.get_implied_volatility_stats(symbol)
    calls = iv_env.provider.calls
    second = await iv_env.service.get_implied_volatility_stats(symbol)
    assert second == first
    token = response_meta.begin()
    try:
        iv_env.provider.error = ProviderConnectionError("down")
        third = await iv_env.service.get_implied_volatility_stats(symbol)
        assert third == first or third.window_end == first.window_end
        assert iv_env.provider.calls <= calls + 1
    finally:
        response_meta.end(token)


async def test_iv_provider_down_without_store_raises(iv_env, monkeypatch):
    monkeypatch.setattr("app.services.volatility_service.date", FrozenDate)
    iv_env.provider.error = ProviderConnectionError("down")
    with pytest.raises(ProviderConnectionError):
        await iv_env.service.get_implied_volatility_stats(parse_symbol("AAPL"))
