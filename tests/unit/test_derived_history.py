from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import response_meta
from app.api import routes_prices
from app.dependencies import get_price_service
from app.models.price import PriceBar
from app.providers.base import BasePriceProvider
from app.providers.registry import ProviderRegistry
from app.services.price_service import PriceService
from app.utils.errors import DataValidationError
from app.utils.symbols import parse_symbol


def utc(*a):
    return datetime(*a, tzinfo=UTC)


class DailyProvider(BasePriceProvider):
    name = "polygon"
    native_intervals = frozenset({"1m", "5m", "1h", "1d"})

    def __init__(self):
        self.calls = []

    async def get_last_price(self, *a, **k):
        raise NotImplementedError

    async def test_connection(self):
        return {}

    async def get_historical_prices(
        self, symbol, interval, start, end, extended_hours=False, sec_type="stock"
    ):
        self.calls.append((interval, start, end))
        bars = []
        for day in range(2, 9):  # Mon 2026-11-02 .. Sun 2026-11-08
            stamp = utc(2026, 11, day)
            if stamp.weekday() < 5 and start <= stamp <= end:
                bars.append(
                    PriceBar(
                        symbol=symbol, start=stamp, end=stamp, open=Decimal(day),
                        high=Decimal(day + 1), low=Decimal(day - 1),
                        close=Decimal(day), volume=10, provider="polygon",
                    )
                )
        return bars


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(ProviderRegistry, "_initialize_providers", lambda self: None)
    registry = ProviderRegistry()
    provider = DailyProvider()
    registry._providers = {"polygon": provider}
    registry.default_price_provider = "polygon"
    return PriceService(registry), provider


async def test_weekly_request_inside_one_week_is_widened(env):
    service, provider = env
    bars = await service.get_historical_prices(
        parse_symbol("AAPL"), "1W", utc(2026, 11, 3), utc(2026, 11, 5), provider_name="polygon"
    )
    assert provider.calls == [("1d", utc(2026, 11, 2), utc(2026, 11, 8, 23, 59, 59))]
    assert len(bars) == 1
    assert (bars[0].open, bars[0].high, bars[0].low, bars[0].close, bars[0].volume) == (
        Decimal(2), Decimal(7), Decimal(1), Decimal(6), 50,
    )
    assert bars[0].source_interval == "1d"


async def test_native_interval_passes_through_unmarked(env):
    service, provider = env
    bars = await service.get_historical_prices(
        parse_symbol("AAPL"), "1d", utc(2026, 11, 2), utc(2026, 11, 3), provider_name="polygon"
    )
    assert provider.calls[0][0] == "1d"
    assert all(b.source_interval is None for b in bars)


async def test_unsupported_interval_rejected_before_provider_call(env):
    service, provider = env
    for interval in ("3h", "30m", "1mo"):
        with pytest.raises(DataValidationError) as error:
            await service.get_historical_prices(
                parse_symbol("AAPL"), interval, utc(2026, 11, 2), utc(2026, 11, 3),
                provider_name="polygon",
            )
        assert error.value.details["native_intervals"] == ["1d", "1h", "1m", "5m"]
        assert error.value.details["derived_intervals"] == ["15m", "4h", "1w"]
    assert provider.calls == []


async def test_fetch_time_is_recorded_for_derived_response(env):
    service, _ = env
    token = response_meta.begin()
    try:
        await service.get_historical_prices(
            parse_symbol("AAPL"), "1w", utc(2026, 11, 3), utc(2026, 11, 5), provider_name="polygon"
        )
        assert response_meta.current().data_as_of is not None
    finally:
        response_meta.end(token)


def test_route_meta_and_csv_header(env, monkeypatch):
    service, _ = env
    app = FastAPI()
    app.include_router(routes_prices.router)
    app.dependency_overrides[get_price_service] = lambda: service
    client = TestClient(app, raise_server_exceptions=False)
    params = {"interval": "1w", "start": "2026-11-03", "end": "2026-11-05", "provider": "polygon"}
    body = client.get("/prices/AAPL/history", params=params).json()
    assert body["meta"]["data_as_of"]
    assert "stale" not in body["meta"] or body["meta"]["stale"] is None
    assert body["data"][0]["source_interval"] == "1d"
    csv = client.get("/prices/AAPL/history", params={**params, "format": "csv"})
    assert csv.headers["x-mdh-data-as-of"]
    assert "source_interval" in csv.text.splitlines()[0]
    error = client.get("/prices/AAPL/history", params={**params, "interval": "3h"})
    assert error.status_code == 500  # AppError handler is registered by the app
