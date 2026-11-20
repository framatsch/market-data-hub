"""Request-local timing shared by async tasks and worker threads."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Literal

import structlog
from starlette.types import Scope

from app.utils.errors import DataValidationError
from app.utils.symbols import parse_symbol

Layer = Literal["redis", "redis-write", "db", "provider"]
Interval = tuple[float, float]
CacheStatus = Literal["hit", "miss", "bypass"]
StoreOutcome = Literal["hit", "partial", "miss", "stale"]
DataSource = Literal["redis", "postgres", "provider", "postgres+provider"]
_TIMED_LAYERS: tuple[Layer, ...] = ("redis", "db", "provider", "redis-write")

PROVIDER_OPERATIONS = frozenset({
    "get_historical_prices", "get_last_price", "get_market_status",
    "get_company_profile", "search_companies", "get_option_chain", "get_option_quote",
    "get_company_news", "get_upcoming_earnings", "get_symbol_earnings",
    "get_earnings_for_date", "get_earnings_history", "get_implied_volatility",
    "get_implied_volatility_history",
})

DATA_ROUTES = {
    "/prices/{symbol}/history": "prices:history",
    "/prices/{symbol}/last": "prices:last",
    "/options/{symbol}/chain": "options:chain",
    "/options/{symbol}/quote/{option_id}": "options:quote",
    "/market-status": "market-status",
    "/companies/{symbol}": "companies:profile",
    "/companies/search": "companies:search",
    "/companies/{symbol}/news": "companies:news",
    "/companies/{symbol}/earnings": "companies:earnings",
    "/volatility/{symbol}": "volatility:snapshot",
    "/volatility/{symbol}/history": "volatility:history",
    "/volatility/{symbol}/stats": "volatility:stats",
    "/earnings/calendar": "earnings:calendar",
    "/earnings/next": "earnings:next",
}

MCP_DATA_TOOLS = {
    "get_historical_prices": "prices:history",
    "get_last_price": "prices:last",
    "get_option_chain": "options:chain",
    "get_option_quote": "options:quote",
    "get_market_status": "market-status",
    "get_company_profile": "companies:profile",
    "search_companies": "companies:search",
    "get_company_news": "companies:news",
    "get_implied_volatility": "volatility:snapshot",
    "get_implied_volatility_history": "volatility:history",
    "get_implied_volatility_stats": "volatility:stats",
    "get_earnings_calendar": "earnings:calendar",
    "get_next_earnings": "earnings:next",
}


@dataclass(slots=True)
class RequestTelemetry:
    request_id: str
    channel: Literal["http", "mcp"]
    start: float = field(default_factory=perf_counter)
    endpoint: str = "other"
    symbol: str | None = None
    spans: dict[Layer, list[Interval]] = field(default_factory=dict)
    cache_status: CacheStatus = "bypass"
    ttl_seconds: int | None = None
    store_outcome: StoreOutcome | None = None
    data_provider: str | None = None
    provider_names: set[str] = field(default_factory=set)
    earnings_fallback_hit: bool = False
    http_scope: Scope | None = None
    response_timing: RequestTiming | None = None
    miss_keys: set[str] = field(default_factory=set)
    closed: bool = False

    def record_span(self, layer: Layer, start: float, end: float) -> None:
        self.spans.setdefault(layer, []).append((start, end))

    def endpoint_key(self) -> str:
        scope = self.http_scope
        if scope is not None and scope.get("method") == "GET":
            return DATA_ROUTES.get(getattr(scope.get("route"), "path", ""), "other")
        return self.endpoint

    def source(self) -> DataSource:
        if self.cache_status == "hit":
            return "redis"
        if self.store_outcome in ("hit", "stale"):
            return "postgres"
        if self.store_outcome == "partial":
            return "postgres+provider"
        return "redis" if self.earnings_fallback_hit else "provider"

    def finish(self, until: float) -> RequestTiming:
        if self.response_timing is None:
            self.response_timing = RequestTiming(
                elapsed=until - self.start,
                layers={
                    layer: union_ms(self.spans[layer], self.start, until)
                    for layer in _TIMED_LAYERS if layer in self.spans
                },
            )
        return self.response_timing


@dataclass(slots=True, frozen=True)
class RequestTiming:
    elapsed: float
    layers: dict[Layer, float]

    def server_timing(self, telemetry: RequestTelemetry, success: bool) -> str:
        entries = []
        if success:
            for layer in _TIMED_LAYERS:
                if layer not in self.layers or (layer == "db" and telemetry.store_outcome is None):
                    continue
                desc = ""
                if layer == "redis":
                    desc = f';desc="{telemetry.cache_status}"'
                elif layer == "db":
                    desc = f';desc="{telemetry.store_outcome}"'
                elif layer == "provider":
                    desc = f';desc="{telemetry.data_provider or "none"}"'
                entries.append(f"{layer}{desc};dur={self.layers[layer]:.1f}")
        entries.append(f"total;dur={self.elapsed * 1000:.1f}")
        return ", ".join(entries)

    def log_fields(self, telemetry: RequestTelemetry, success: bool) -> dict[str, Any]:
        return {
            "channel": telemetry.channel,
            "endpoint": telemetry.endpoint_key(),
            "symbol": telemetry.symbol,
            "data_source": telemetry.source() if success else None,
            "data_provider": telemetry.data_provider,
            "cache_status": telemetry.cache_status,
            "ttl_seconds": telemetry.ttl_seconds,
            "redis_ms": round(self.layers.get("redis", 0), 1),
            "db_ms": round(self.layers.get("db", 0), 1),
            "provider_ms": round(self.layers.get("provider", 0), 1),
            "total_ms": round(self.elapsed * 1000, 1),
        }


request_telemetry: ContextVar[RequestTelemetry | None] = ContextVar(
    "mdh_request_telemetry", default=None
)


def current_telemetry() -> RequestTelemetry | None:
    return request_telemetry.get()


def bind_data_provider(*names: str) -> None:
    """Record answer provenance without changing the existing `provider` log field."""
    structlog.contextvars.bind_contextvars(provider=names[0] if len(names) == 1 else ",".join(names))
    if (telemetry := current_telemetry()) is not None:
        telemetry.data_provider = "+".join(name for name in names if isinstance(name, str)) or None


def canonical_telemetry_symbol(raw: Any, sec_type: Any = None) -> str | None:
    if not isinstance(raw, str):
        return None
    try:
        return parse_symbol(raw, sec_type if isinstance(sec_type, str) else None).canonical
    except DataValidationError:
        return None


@asynccontextmanager
async def span(
    layer: Layer, operation: str | None = None, *, provider: str | None = None
) -> AsyncIterator[None]:
    telemetry = current_telemetry()
    if telemetry is None and operation is None:
        yield
        return
    start = perf_counter()
    error: BaseException | None = None
    try:
        yield
    except BaseException as exc:
        error = exc
        raise
    finally:
        if layer != "provider" or not isinstance(error, asyncio.CancelledError):
            end = perf_counter()
            if telemetry is not None:
                telemetry.record_span(layer, start, end)
            if operation is not None:
                from app.observability.metrics import record_operation

                endpoint = telemetry.endpoint_key() if telemetry is not None else "other"
                record_operation(layer, endpoint, operation, provider, end - start, error)


def union_ms(spans: Iterable[Interval], start: float, until: float) -> float:
    """Return the wall time covered by the intervals within the request window."""
    if isinstance(spans, list) and len(spans) == 1:
        first, last = spans[0]
        return max(0.0, min(last, until) - max(first, start)) * 1000
    covered = 0.0
    right = start
    for left, end in sorted(spans):
        left = max(left, right)
        end = min(end, until)
        if end > left:
            covered += end - left
            right = end
    return covered * 1000
