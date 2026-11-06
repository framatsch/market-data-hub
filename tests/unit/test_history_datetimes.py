# market-data-hub - FastAPI data service for market and company data
# Copyright (C) 2026  Market Data Hub Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""History request dates share UTC semantics across REST, MCP and providers."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import cache as response_cache
from app.api import mcp, routes_prices
from app.dependencies import get_price_service
from app.models.price import PriceBar
from app.providers.base import BasePriceProvider
from app.providers.registry import ProviderRegistry
from app.services.price_service import PriceService

NOW = datetime(2026, 11, 6, 12, 30, tzinfo=UTC)
START = datetime(2026, 11, 1, tzinfo=UTC)
END = datetime(2026, 11, 5, 10, tzinfo=UTC)
OLD_END = datetime(2025, 3, 1, 15, tzinfo=UTC)

RANGES = [
    pytest.param({}, NOW - timedelta(days=30), NOW, id="defaults"),
    pytest.param({"start": "2026-11-01T00:00:00Z"}, START, NOW, id="z-start-no-end"),
    pytest.param({"start": "2026-11-01T02:00:00+02:00"}, START, NOW, id="offset-start-no-end"),
    pytest.param({"start": "2026-11-01T00:00:00"}, START, NOW, id="naive-start-no-end"),
    pytest.param({"start": "2026-11-01T00:00:00Z", "end": "2026-11-05T10:00:00"}, START, END, id="aware-start-naive-end"),
    pytest.param({"start": "2026-11-01T00:00:00", "end": "2026-11-05T10:00:00Z"}, START, END, id="naive-start-aware-end"),
    pytest.param({"start": "2026-11-01T00:00:00", "end": "2026-11-05T10:00:00"}, START, END, id="both-naive"),
    pytest.param({"start": "2026-11-01T02:00:00+02:00", "end": "2026-11-05T05:00:00-05:00"}, START, END, id="different-offsets"),
    pytest.param({"end": "2025-03-01T10:00:00-05:00"}, OLD_END - timedelta(days=30), OLD_END, id="end-only-default-start"),
]


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        # A non-UTC host catches merely relabelling a local datetime as UTC.
        if tz is None:
            return NOW.astimezone(timezone(timedelta(hours=2))).replace(tzinfo=None)
        return NOW.astimezone(tz)


class RecordingPriceProvider(BasePriceProvider):
    name = "ibkr"

    def __init__(self):
        self.calls = []

    async def get_last_price(self, *args, **kwargs):
        raise NotImplementedError

    async def test_connection(self):
        return {"success": True, "status_code": 200, "message": "test provider"}

    async def get_historical_prices(
        self, symbol, interval, start, end, extended_hours=False, sec_type="stock"
    ):
        # This is the same arithmetic that raised in the real IBKR provider.
        duration = end - start
        self.calls.append((start, end, duration))
        return [PriceBar(
            symbol=symbol, start=START, end=START,
            open=Decimal("100.01"), high=Decimal("102.03"),
            low=Decimal("99.99"), close=Decimal("101.02"),
            volume=100, provider=self.name,
        )]


@pytest.fixture
def history_env(monkeypatch):
    monkeypatch.setattr(ProviderRegistry, "_initialize_providers", lambda self: None)
    registry = ProviderRegistry()
    provider = RecordingPriceProvider()
    registry._providers = {"ibkr": provider}
    registry.default_price_provider = "ibkr"
    service = PriceService(registry)
    monkeypatch.setattr(routes_prices, "datetime", FrozenDateTime)
    monkeypatch.setattr(mcp, "datetime", FrozenDateTime)
    monkeypatch.setattr(mcp, "_price_service", lambda: service)
    return SimpleNamespace(service=service, provider=provider)


@pytest.fixture(params=[False, True], ids=["cache-disabled", "cache-enabled"])
def cache_mode(request, cache_redis):
    if not request.param:
        response_cache._disable_cache()
    return request.param


@pytest.fixture
def history_client(history_env, cache_mode):
    app = FastAPI()
    app.include_router(routes_prices.router)
    app.dependency_overrides[get_price_service] = lambda: history_env.service
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def assert_utc_range(calls, start, end, count):
    assert len(calls) == count
    for actual_start, actual_end, duration in calls:
        assert actual_start.tzinfo is UTC
        assert actual_end.tzinfo is UTC
        assert actual_start == start
        assert actual_end == end
        assert duration == end - start


@pytest.mark.parametrize("start,end", [
    (START.replace(tzinfo=None), END.replace(tzinfo=None)),
    (START, END.replace(tzinfo=None)),
    (START.replace(tzinfo=None), END),
    (START.astimezone(timezone(timedelta(hours=2))), END.astimezone(timezone(timedelta(hours=-5)))),
])
async def test_service_normalizes_both_request_dates(history_env, start, end):
    bars = await history_env.service.get_historical_prices("AAPL", "1d", start, end)
    assert_utc_range(history_env.provider.calls, START, END, 1)
    assert bars[0].start == START
    assert bars[0].close == Decimal("101.02")


@pytest.mark.parametrize("params,start,end", RANGES)
@pytest.mark.parametrize("format", ["json", "csv"])
def test_rest_history_dates(
    history_client, history_env, cache_mode, params, start, end, format
):
    params = {**params, "provider": "ibkr", "format": format}
    first = history_client.get("/prices/AAPL/history", params=params)
    second = history_client.get("/prices/AAPL/history", params=params)
    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    assert_utc_range(history_env.provider.calls, start, end, 1 if cache_mode else 2)
    if cache_mode:
        assert first.headers["x-fastapi-cache"] == "MISS"
        assert second.headers["x-fastapi-cache"] == "HIT"
    else:
        assert "x-fastapi-cache" not in second.headers
    if format == "csv":
        assert first.headers["content-type"].startswith("text/csv")
        assert first.headers["content-disposition"] == second.headers["content-disposition"]


@pytest.mark.parametrize("params,start,end", RANGES)
async def test_mcp_history_dates(history_env, cache_mode, params, start, end):
    args = {f"{key}_date": value for key, value in params.items()}
    args.update({"symbol": "AAPL", "interval": "1d", "provider": "ibkr"})
    first = await mcp._tool_get_historical_prices(args)
    second = await mcp._tool_get_historical_prices(args)
    assert first == second
    assert "AAPL" in first["content"][0]["text"]
    assert_utc_range(history_env.provider.calls, start, end, 1 if cache_mode else 2)
