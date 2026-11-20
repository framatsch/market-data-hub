import asyncio
from unittest.mock import AsyncMock

import pytest

from app import cache, response_meta
from app.observability.metrics import release_cache_misses
from app.observability.telemetry import (
    RequestTelemetry,
    current_telemetry,
    request_telemetry,
    span,
    union_ms,
)
from app.providers.base import BaseOptionsProvider, BasePriceProvider
from app.providers.metered import MeteredHttpProvider


@pytest.mark.parametrize(
    ("spans", "start", "until", "expected"),
    [
        ([], 0, 10, 0),
        ([(5, 6), (1, 2)], 0, 10, 2000),
        ([(1, 4), (3, 5)], 0, 10, 4000),
        ([(1, 5), (2, 3)], 0, 10, 4000),
        ([(-2, -1), (-1, 2), (3, 8), (9, 10)], 0, 5, 4000),
    ],
)
def test_union_ms(spans, start, until, expected):
    assert union_ms(spans, start, until) == expected


async def test_spans_share_context_across_tasks_and_worker_threads():
    telemetry = RequestTelemetry("test", "http")
    token = request_telemetry.set(telemetry)

    async def record():
        assert current_telemetry() is telemetry
        async with span("provider"):
            await asyncio.sleep(0)

    try:
        await asyncio.gather(record(), record(), asyncio.to_thread(asyncio.run, record()))
        assert len(telemetry.spans["provider"]) == 3
        assert all(start >= telemetry.start and end >= start for start, end in telemetry.spans["provider"])
    finally:
        request_telemetry.reset(token)
    assert current_telemetry() is None


async def test_span_without_context_is_a_no_op(monkeypatch):
    def unexpected_clock_read():
        pytest.fail("span without telemetry read the clock")

    monkeypatch.setattr("app.observability.telemetry.perf_counter", unexpected_clock_read)
    async with span("redis"):
        assert current_telemetry() is None


async def test_cache_hit_keeps_remaining_ttl_after_policy_change(cache_redis):
    backend = cache.FastAPICache.get_backend()
    key = "mdh:options:chain:AAPL:provider=schwab"
    cache.policy.values.extend_when_market_closed = False
    cache.policy.values.option_chain_seconds = 900
    await backend.set(key, b"cached")
    cache.policy.values.option_chain_seconds = 0
    telemetry = RequestTelemetry("test", "http")
    token = request_telemetry.set(telemetry)
    try:
        assert await backend.get_with_ttl(key) == (900, b"cached")
        assert (telemetry.cache_status, telemetry.ttl_seconds) == ("hit", 900)
        assert telemetry.data_provider == "schwab"
        assert set(telemetry.spans) == {"redis"}
    finally:
        release_cache_misses(telemetry)
        request_telemetry.reset(token)


@pytest.mark.parametrize(
    ("kind", "expected"),
    [("upcoming", "earningsapi"), ("reported", "financialdatasets"),
     ("all", "earningsapi+financialdatasets")],
)
async def test_earnings_cache_hit_attributes_selected_roles(cache_redis, monkeypatch, kind, expected):
    monkeypatch.setattr(cache.registry, "default_earnings_upcoming_provider", "earningsapi")
    monkeypatch.setattr(cache.registry, "default_earnings_history_provider", "financialdatasets")
    loader = AsyncMock(return_value=[])
    await cache.cached_call("earnings:calendar", None, {"kind": kind}, loader)
    telemetry = RequestTelemetry("test", "mcp")
    token = request_telemetry.set(telemetry)
    try:
        await cache.cached_call("earnings:calendar", None, {"kind": kind}, loader)
        assert telemetry.cache_status == "hit"
        assert telemetry.data_provider == expected
        assert loader.await_count == 1
    finally:
        release_cache_misses(telemetry)
        request_telemetry.reset(token)


@pytest.mark.parametrize("mode", ["miss", "no-cache", "refresh", "zero", "offline", "stale"])
async def test_cache_status_and_spans(cache_redis, mode):
    cache.policy.values.option_chain_seconds = 0 if mode == "zero" else 900
    cache.policy.values.extend_when_market_closed = False
    cache_redis.fail = mode == "offline"
    telemetry = RequestTelemetry("test", "mcp")
    token = request_telemetry.set(telemetry)
    meta_token = response_meta.begin(no_cache=mode == "no-cache")

    async def loader():
        if mode == "stale":
            response_meta.current().mark_stale("test")
        return []

    try:
        await cache.cached_call("options:chain", None, {}, loader, refresh=mode == "refresh")
        assert telemetry.cache_status == ("miss" if mode == "miss" else "bypass")
        assert telemetry.ttl_seconds == (900 if mode == "miss" else None)
        assert ("redis" in telemetry.spans) == (mode != "refresh")
        assert ("redis-write" in telemetry.spans) == (mode in {"miss", "no-cache", "refresh"})
    finally:
        response_meta.end(meta_token)
        release_cache_misses(telemetry)
        request_telemetry.reset(token)


async def test_nested_provider_call_only_records_outermost_span():
    class FakeProvider(MeteredHttpProvider, BaseOptionsProvider, BasePriceProvider):
        name = "fake"

        def __init__(self):
            pass

        async def get_option_chain(self, symbol, expiry, **kwargs):
            return await self.get_last_price(symbol)

        async def get_option_quote(self, *args, **kwargs):
            raise NotImplementedError

        async def get_historical_prices(self, *args, **kwargs):
            raise NotImplementedError

        async def get_last_price(self, symbol, **kwargs):
            return symbol

    telemetry = RequestTelemetry("test", "http")
    token = request_telemetry.set(telemetry)
    try:
        provider = FakeProvider()
        assert await provider.get_option_chain("AAPL", None) == "AAPL"
        assert (await provider.test_connection())["success"] is True
        assert len(telemetry.spans["provider"]) == 1
        assert telemetry.provider_names == {"fake"}
    finally:
        request_telemetry.reset(token)
