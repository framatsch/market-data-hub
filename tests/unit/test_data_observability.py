import asyncio
import re
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import structlog
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families
from structlog.testing import capture_logs

from app import cache
from app.api import mcp
from app.dependencies import get_options_service, get_price_service
from app.main import app
from app.models.options import OptionChain
from app.models.price import PriceBar, PriceQuote
from app.observability import middleware
from app.observability.metrics import REGISTRY, record_data_request, record_operation
from app.observability.telemetry import RequestTelemetry, span
from app.providers.base import BaseOptionsProvider, BasePriceProvider
from app.providers.registry import ProviderRegistry
from app.services import price_service
from app.services.options_service import OptionsService
from app.services.price_service import PriceService
from app.store import engine, repository
from app.store.sync import HistorySync
from app.utils.errors import DataNotFoundError, ProviderTimeoutError

WEDNESDAY = datetime(2026, 11, 18, 16, tzinfo=UTC)
SATURDAY = datetime(2026, 11, 21, 16, tzinfo=UTC)
CHAIN = "/options/AAPL/chain?expiry=2026-12-18"
LAST = "/prices/AAPL/last"
HISTORY = "/prices/AAPL/history?interval=1d&start=2026-11-16&end=2026-11-18"


def bar(day: int, provider: str) -> PriceBar:
    start = datetime(2026, 11, day, tzinfo=UTC)
    return PriceBar(
        symbol="AAPL", start=start, end=start + timedelta(days=1), open="1",
        high="2", low="1", close="2", volume=1, provider=provider,
    )


class Provider(BasePriceProvider, BaseOptionsProvider):
    name = "schwab"
    fails = False
    chain_calls = 0
    chain_ready = None
    chain_release = None
    chain_fails = False

    async def get_option_chain(self, symbol, expiry, **kwargs):
        self.chain_calls += 1
        if self.chain_ready is not None:
            self.chain_ready.put_nowait(self.chain_calls)
            await self.chain_release.wait()
        if self.chain_fails:
            raise ProviderTimeoutError(self.name)
        return OptionChain(underlying_symbol=symbol, expiry=expiry, provider=self.name, options=[])

    async def get_option_quote(self, *args, **kwargs):
        raise NotImplementedError

    async def get_last_price(self, symbol, *args):
        if self.fails:
            raise ProviderTimeoutError(self.name)
        return PriceQuote(symbol=symbol, price="2", currency="USD", timestamp=WEDNESDAY, provider=self.name)

    async def get_historical_prices(self, *args, **kwargs):
        if self.fails:
            raise ProviderTimeoutError(self.name)
        return [bar(17, self.name), bar(18, self.name)]

    async def test_connection(self):
        return {}


@pytest.fixture
def http_data(cache_redis, monkeypatch):
    monkeypatch.setattr(ProviderRegistry, "_initialize_providers", lambda self: None)
    registry = ProviderRegistry()
    provider = Provider()
    registry._providers = {provider.name: provider}
    registry.default_price_provider = registry.default_options_provider = provider.name
    monkeypatch.setattr(cache.registry, "default_price_provider", provider.name)
    monkeypatch.setattr(cache.registry, "default_options_provider", provider.name)
    monkeypatch.setitem(app.dependency_overrides, get_price_service, lambda: PriceService(registry))
    monkeypatch.setitem(app.dependency_overrides, get_options_service, lambda: OptionsService(registry))
    cache.policy.values.extend_when_market_closed = False
    cache.policy.values.option_chain_seconds = 900
    return TestClient(app), provider


@pytest.fixture
def in_memory_store(monkeypatch):
    """Fake only the transactional boundary and repository, retaining the real sync planner."""
    @asynccontextmanager
    async def transaction():
        yield

    @asynccontextmanager
    async def session_factory():
        yield SimpleNamespace(begin=transaction)

    def configure(mode: str) -> None:
        now = WEDNESDAY if mode == "partial" else SATURDAY

        class FixedClockHistory(HistorySync):
            async def serve(self, *args, **kwargs):
                return await super().serve(*args, **kwargs, now=now)

        monkeypatch.setattr(price_service, "history_sync", FixedClockHistory())
        monkeypatch.setattr(engine, "_sessions", session_factory)
        monkeypatch.setattr(engine, "_state", "connected")
        monkeypatch.setattr(engine, "_retry_at", 0.0)
        monkeypatch.setattr(engine, "_failed", False)
        key = repository.SeriesKey("prices", "AAPL", "schwab", "1d")
        begin = None if mode == "fallback" else bar(16, "schwab").start
        end = None if mode == "fallback" else bar(17 if mode == "partial" else 20, "schwab").start
        series = repository.Series(1, key, "stock", None, None, begin, end, now - timedelta(hours=1), None)
        alternative = replace(
            series, id=2, key=replace(key, provider="ibkr"),
            covered_from=bar(16, "ibkr").start, covered_to=bar(20, "ibkr").start,
        )

        async def read_bars(session, series, start, end):
            return [bar(17, series.key.provider)]

        monkeypatch.setattr(repository, "get_or_create_series", AsyncMock(return_value=series))
        monkeypatch.setattr(repository, "get_series", AsyncMock(return_value=series))
        monkeypatch.setattr(repository, "update_series", AsyncMock())
        monkeypatch.setattr(repository, "covering_price_series", AsyncMock(return_value=[alternative]))
        monkeypatch.setattr(repository, "read_bars", read_bars)
        monkeypatch.setattr(repository, "newest_bars", AsyncMock(return_value=[bar(17, "schwab")]))
        monkeypatch.setattr(repository, "upsert_bars", AsyncMock())

    return configure


def timing(response) -> dict[str, str | None]:
    entries = {}
    durations = {}
    for entry in response.headers["Server-Timing"].split(", "):
        match = re.fullmatch(r'(redis|redis-write|db|provider|total)(?:;desc="([^"]+)")?;dur=(\d+\.\d)', entry)
        assert match is not None
        name, desc, duration = match.groups()
        entries[name] = desc
        durations[name] = float(duration)
    assert all(value <= durations["total"] for value in durations.values())
    return entries


@pytest.mark.parametrize("format", ["json", "csv"])
def test_chain_miss_hit_and_revalidation(http_data, format):
    client, provider = http_data
    url = f"{CHAIN}&format={format}"
    miss = client.get(url)
    assert miss.status_code == 200
    assert miss.headers["X-FastAPI-Cache"] == "MISS"
    assert miss.headers["X-Data-Source"] == "provider"
    assert miss.headers["X-Data-Provider"] == "schwab"
    assert list(timing(miss).items()) == [
        ("redis", "miss"), ("provider", "schwab"), ("redis-write", None), ("total", None),
    ]
    hit = client.get(url)
    conditional = client.get(url, headers={"If-None-Match": hit.headers["etag"]})
    assert conditional.status_code == 304
    for response in (hit, conditional):
        assert response.headers["X-FastAPI-Cache"] == "HIT"
        assert response.headers["X-Data-Source"] == "redis"
        assert response.headers["X-Data-Provider"] == "schwab"
        assert list(timing(response).items()) == [("redis", "hit"), ("total", None)]
    assert miss.content == hit.content
    assert provider.chain_calls == 1


@pytest.mark.parametrize(
    ("mode", "source", "outcome", "provider"),
    [("hit", "postgres", "hit", "schwab"), ("partial", "postgres+provider", "partial", "schwab"),
     ("fallback", "postgres", "stale", "ibkr")],
)
def test_history_store_attribution(http_data, in_memory_store, mode, source, outcome, provider):
    in_memory_store(mode)
    client, fake_provider = http_data
    fake_provider.fails = mode == "fallback"
    response = client.get(HISTORY)
    assert response.status_code == 200
    assert response.headers["X-Data-Source"] == source
    assert response.headers["X-Data-Provider"] == provider
    entries = timing(response)
    assert entries["db"] == outcome
    assert ("provider" in entries) == (mode != "hit")
    if mode == "fallback":
        assert response.json()["meta"]["source_provider"] == "ibkr"
        assert entries["redis"] == "bypass"
    else:
        assert entries["redis"] == "miss"


def test_uncached_refresh_and_error(http_data):
    client, provider = http_data
    uncached = client.get(LAST)
    assert timing(uncached) == {"provider": "schwab", "total": None}
    assert "X-FastAPI-Cache" not in uncached.headers
    no_cache = client.get(CHAIN, headers={"Cache-Control": "no-cache"})
    assert timing(no_cache)["redis"] == "bypass"
    assert no_cache.headers["X-FastAPI-Cache"] == "MISS"
    provider.fails = True
    failed = client.get(LAST)
    assert failed.status_code == 503
    assert timing(failed) == {"total": None}
    assert "X-Data-Source" not in failed.headers and "X-Data-Provider" not in failed.headers


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(f"mdh_{name}", labels) or 0


def total_data_requests() -> float:
    return sum(
        sample.value
        for family in REGISTRY.collect() if family.name == "mdh_data_requests"
        for sample in family.samples if sample.name == "mdh_data_requests_total"
    )


def test_metrics_count_successes_only_and_do_not_expose_symbol(http_data, in_memory_store):
    in_memory_store("hit")
    client, provider = http_data
    samples = {
        "miss": {"channel": "http", "endpoint": "options:chain", "source": "provider", "provider": "schwab", "cache_status": "miss"},
        "hit": {"channel": "http", "endpoint": "options:chain", "source": "redis", "provider": "schwab", "cache_status": "hit"},
        "store": {"channel": "http", "endpoint": "prices:history", "source": "postgres", "provider": "schwab", "cache_status": "miss"},
    }
    before = {key: sample("data_requests_total", **labels) for key, labels in samples.items()}
    total = total_data_requests()
    db_before = sample("db_operation_duration_seconds_count", endpoint="prices:history", operation="write", status="ok")
    for url in (CHAIN, CHAIN, HISTORY):
        assert client.get(url).status_code == 200
    provider.fails = True
    assert client.get(LAST).status_code == 503
    for key, labels in samples.items():
        assert sample("data_requests_total", **labels) == before[key] + 1
    assert total_data_requests() == total + 3
    assert sample("db_operation_duration_seconds_count", endpoint="prices:history", operation="write", status="ok") > db_before
    assert sample("provider_request_duration_seconds_count", provider="schwab", operation="get_last_price", status="timeout") >= 1
    body = client.get("/metrics").text
    assert "AAPL" not in body
    families = list(text_string_to_metric_families(body))
    for name in (
        "data_request_duration_seconds", "cache_operation_duration_seconds",
        "db_operation_duration_seconds", "provider_request_duration_seconds",
    ):
        family = next(family for family in families if family.name == f"mdh_{name}")
        assert {row.labels["le"] for row in family.samples if "le" in row.labels} == {
            "0.001", "0.0025", "0.005", "0.01", "0.025", "0.05", "0.1", "0.25", "0.5",
            "1.0", "2.5", "5.0", "10.0", "30.0", "+Inf",
        }


def test_metric_labels_are_bounded_and_composed_provider_is_multiple():
    labels = {"channel": "http", "endpoint": "other", "source": "provider", "cache_status": "bypass"}
    for value, expected in (("private-user-input+oops", "none"), ("earningsapi+financialdatasets", "multiple")):
        before = sample("data_requests_total", provider=expected, **labels)
        record_data_request(RequestTelemetry("test", "http", endpoint="unbounded-symbol", data_provider=value), 0.002)
        assert sample("data_requests_total", provider=expected, **labels) == before + 1
    before = sample("cache_operation_duration_seconds_count", endpoint="other", operation="read", status="error")
    record_operation("redis", "unbounded-symbol", "unbounded-operation", None, 0.002, RuntimeError())
    assert sample("cache_operation_duration_seconds_count", endpoint="other", operation="read", status="error") == before + 1
    before = sample("provider_request_duration_seconds_count", provider="none", operation="other", status="error")
    record_operation("provider", "other", "unbounded-operation", "private-user-input", 0.002, RuntimeError())
    assert sample("provider_request_duration_seconds_count", provider="none", operation="other", status="error") == before + 1


@pytest.mark.parametrize(
    ("error", "status"),
    [(None, "success"), (DataNotFoundError("price", "AAPL"), "not_found"),
     (httpx.ReadTimeout("timeout"), "timeout"), (TimeoutError(), "timeout"),
     (ValueError(), "error"), (asyncio.CancelledError(), None)],
)
async def test_operation_metrics_outside_request_and_cancellation(error, status):
    counts = {value: sample("provider_request_duration_seconds_count", provider="lseg", operation="get_last_price", status=value)
              for value in ("success", "not_found", "timeout", "error")}

    async def run():
        async with span("provider", "get_last_price", provider="lseg"):
            if error is not None:
                raise error

    if error is None:
        await run()
    else:
        with pytest.raises(type(error)):
            await run()
    for value, before in counts.items():
        assert sample("provider_request_duration_seconds_count", provider="lseg", operation="get_last_price", status=value) == before + (value == status)


async def test_concurrent_miss_counts_overlap_only_and_releases_failed_requests(http_data):
    _, provider = http_data
    provider.chain_ready = asyncio.Queue()
    provider.chain_release = asyncio.Event()
    provider.chain_fails = True  # same request key can miss again once each failure completes
    baseline = sample("cache_concurrent_miss_total", endpoint="options:chain")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        first = asyncio.create_task(client.get(CHAIN))
        second = None
        try:
            await asyncio.wait_for(provider.chain_ready.get(), 2)
            second = asyncio.create_task(client.get(CHAIN))
            await asyncio.wait_for(provider.chain_ready.get(), 2)
            assert sample("cache_concurrent_miss_total", endpoint="options:chain") == baseline + 1
        finally:
            provider.chain_release.set()
            results = await asyncio.gather(*(request for request in (first, second) if request is not None))
        assert [result.status_code for result in results] == [503, 503]
        for _ in range(2):
            assert (await client.get(CHAIN)).status_code == 503
        assert sample("cache_concurrent_miss_total", endpoint="options:chain") == baseline + 1
        assert provider.chain_calls == 4


def test_http_audit_fields_for_hit_store_provider_and_error(http_data, in_memory_store, monkeypatch):
    in_memory_store("hit")
    client, provider = http_data
    with capture_logs() as logs:
        monkeypatch.setattr(middleware, "audit_log", structlog.get_logger())
        responses = [client.get(url) for url in (CHAIN, CHAIN, HISTORY)]
        provider.fails = True
        responses.append(client.get(LAST))
    completed = [entry for entry in logs if entry["event"] == "request_completed"]
    assert [entry["data_source"] for entry in completed] == ["provider", "redis", "postgres", None]
    assert [entry["cache_status"] for entry in completed] == ["miss", "hit", "miss", "bypass"]
    assert [entry["ttl_seconds"] for entry in completed][:2] == [900, 900]
    assert completed[-1]["ttl_seconds"] is None
    for response, entry in zip(responses, completed, strict=True):
        assert entry["status_code"] == response.status_code
        assert entry["request_id"] == response.headers["X-Request-ID"]
        assert entry["symbol"] == "AAPL"
        assert entry["channel"] == "http"
        assert entry["total_ms"] == float(response.headers["Server-Timing"].rsplit("=", 1)[1])
        assert all(isinstance(entry[name], (int, float)) for name in ("redis_ms", "db_ms", "provider_ms"))
        assert "data" not in entry and "payload" not in entry and "options" not in entry


async def test_mcp_metrics_log_and_refresh(http_data, monkeypatch):
    monkeypatch.setattr(mcp, "_options_service", app.dependency_overrides[get_options_service])
    args = {"symbol": "aapl", "expiry": "2026-12-18"}
    labels = {"channel": "mcp", "endpoint": "options:chain", "source": "provider", "provider": "schwab"}
    baselines = {status: sample("data_requests_total", cache_status=status, **labels) for status in ("miss", "bypass")}
    with capture_logs() as logs:
        monkeypatch.setattr(mcp, "audit_log", structlog.get_logger())
        for refresh in (False, True):
            result = await mcp._dispatch("tools/call", {"name": "get_option_chain", "arguments": {**args, "refresh": refresh}})
            assert "content" in result
    tool_logs = [entry for entry in logs if entry["event"] == "mcp_tool_completed"]
    assert len(tool_logs) == 2
    for log, status in zip(tool_logs, ("miss", "bypass"), strict=True):
        assert sample("data_requests_total", cache_status=status, **labels) == baselines[status] + 1
        assert log["tool"] == "get_option_chain" and log["status"] == "ok"
        assert log["channel"] == "mcp" and log["symbol"] == "AAPL"
        assert log["data_provider"] == "schwab" and log["cache_status"] == status
        assert "content" not in log and "arguments" not in log
