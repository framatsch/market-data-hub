from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import response_meta
from app.api import routes_prices
from app.cache import _compose_key
from app.dependencies import get_price_service
from app.utils.symbols import parse_symbol


def key(**params):
    return _compose_key("prices:history", parse_symbol("AAPL"), {"provider": "schwab", **params})


def test_daily_keys_use_the_utc_date():
    a = key(interval="1d", start="2025-03-06T08:55:01.137706+00:00")
    b = key(interval="1d", start="2025-03-06T12:22:29.566314+00:00")
    assert a == b == "mdh:prices:history:AAPL:interval=1d&provider=schwab&start=2025-03-06"
    assert key(interval="1d", start="2025-03-07T00:00:00+00:00") != a
    assert key(interval="1d", start="2025-03-06T23:00:00-05:00").endswith("start=2025-03-07")
    assert key(interval="1d", start="2025-03-06T10:00:00").endswith("start=2025-03-06")


def test_intraday_keys_keep_full_values():
    assert "2026-11-16T14%3A30%3A00" in key(interval="5m", start="2026-11-16T14:30:00Z")


def test_intervals_are_normalized_in_keys():
    assert key(interval="1wk", start="2025-03-06") == key(interval="1w", start="2025-03-06")
    upper = key(interval="1W", start="2025-03-06T08:55:01+00:00")
    assert "interval=1w" in upper and upper.endswith("start=2025-03-06")
    assert "interval=1h" in key(interval="60m")
    assert "interval=4h" in key(interval="4h")
    assert "interval=3x" in key(interval="3x")


class StubService:
    def __init__(self):
        self.calls = 0
        self.stale = False

    async def get_historical_prices(self, *args, **kwargs):
        self.calls += 1
        state = response_meta.current()
        state.record_fetch(datetime(2026, 11, 6, 14, 30, 5, tzinfo=UTC))
        if self.stale:
            state.mark_stale("PROVIDER_TIMEOUT")
        return []


@pytest.fixture
def http(cache_redis):
    service = StubService()
    app = FastAPI()
    app.include_router(routes_prices.router)
    app.dependency_overrides[get_price_service] = lambda: service
    return TestClient(app), service, cache_redis


PARAMS = {"interval": "1d", "provider": "ibkr", "start": "2025-01-01", "end": "2025-02-01"}


def test_data_as_of_survives_cache_hit_and_no_cache_refreshes(http):
    client, service, _ = http
    first = client.get("/prices/AAPL/history", params=PARAMS)
    second = client.get("/prices/AAPL/history", params=PARAMS)
    assert first.headers["x-fastapi-cache"] == "MISS" and second.headers["x-fastapi-cache"] == "HIT"
    assert first.json()["meta"]["data_as_of"] == second.json()["meta"]["data_as_of"]
    assert first.json()["meta"]["data_as_of"].startswith("2026-11-06T14:30:05")
    assert service.calls == 1
    forced = client.get("/prices/AAPL/history", params=PARAMS, headers={"Cache-Control": "no-cache"})
    assert forced.status_code == 200 and service.calls == 2


def test_stale_responses_are_never_cached(http):
    client, service, redis = http
    service.stale = True
    first = client.get("/prices/AAPL/history", params=PARAMS)
    assert first.json()["meta"]["stale"] is True
    assert first.json()["meta"]["stale_reason"] == "PROVIDER_TIMEOUT"
    assert first.headers["cache-control"] == "no-store"
    assert not redis.entries
    service.stale = False
    second = client.get("/prices/AAPL/history", params=PARAMS)
    assert service.calls == 2
    assert second.json()["meta"].get("stale") in (None, False)
    assert redis.entries


def test_csv_carries_the_header(http):
    client, _, _ = http
    csv = client.get("/prices/AAPL/history", params={**PARAMS, "format": "csv"})
    assert csv.headers["x-mdh-data-as-of"].startswith("2026-11-06T14:30:05")
    hit = client.get("/prices/AAPL/history", params={**PARAMS, "format": "csv"})
    assert hit.headers["x-mdh-data-as-of"] == csv.headers["x-mdh-data-as-of"]

