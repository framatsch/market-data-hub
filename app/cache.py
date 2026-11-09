"""Shared response caching: transparent keys, runtime policy and fail-open Redis."""

import asyncio
import base64
import json
import logging
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from functools import wraps
from typing import Annotated, Any, Literal, ParamSpec, TypeVar
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from fastapi import Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from fastapi_cache.backends.redis import RedisBackend
from fastapi_cache.coder import JsonCoder
from fastapi_cache.decorator import cache as library_cache
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
)
from redis import asyncio as aioredis
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.admin.runtime import get_settings_repository
from app.config import settings
from app.market_hours import (
    ET,
    as_utc,
    bar_length_seconds,
    current_period_start,
    market_state,
    next_open,
    next_transition,
)
from app.providers.registry import registry
from app.utils.symbols import ParsedSymbol, parse_symbol

logger = logging.getLogger(__name__)
P = ParamSpec("P")
R = TypeVar("R")
CacheScope = Literal[
    "all",
    "options_chain",
    "historical_prices",
    "company_profile",
    "company_search",
    "company_news",
    "market_status",
    "volatility",
]
Ttl = Annotated[StrictInt, Field(ge=0, le=2592000)]
_request: ContextVar[Request | None] = ContextVar("mdh_cache_request", default=None)
_PATTERNS = {
    "all": "mdh:*",
    "options_chain": "mdh:options:chain:*",
    "historical_prices": "mdh:prices:history:*",
    "company_profile": "mdh:companies:profile:*",
    "company_search": "mdh:companies:search:*",
    "company_news": "mdh:companies:news:*",
    "market_status": "mdh:market-status:*",
    "volatility": "mdh:volatility:*",
}


class CachePolicyValues(BaseModel):
    model_config = ConfigDict(extra="forbid")
    option_chain_seconds: Ttl
    historical_closed_seconds: Ttl
    historical_open_bar_seconds: Ttl
    historical_intraday_seconds: Ttl
    company_profile_seconds: Ttl
    company_search_seconds: Ttl
    company_news_seconds: Ttl
    market_status_seconds: Ttl
    volatility_seconds: Ttl
    extend_when_market_closed: StrictBool


class CachePolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    option_chain_seconds: Ttl | None = None
    historical_closed_seconds: Ttl | None = None
    historical_open_bar_seconds: Ttl | None = None
    historical_intraday_seconds: Ttl | None = None
    company_profile_seconds: Ttl | None = None
    company_search_seconds: Ttl | None = None
    company_news_seconds: Ttl | None = None
    market_status_seconds: Ttl | None = None
    volatility_seconds: Ttl | None = None
    extend_when_market_closed: StrictBool | None = None

    @field_validator("*")
    @classmethod
    def no_explicit_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("Policy values must not be null")
        return value


def policy_defaults() -> CachePolicyValues:
    return CachePolicyValues(
        option_chain_seconds=settings.CACHE_TTL_OPTION_CHAIN_SECONDS,
        historical_closed_seconds=settings.CACHE_TTL_HISTORICAL_CLOSED_SECONDS,
        historical_open_bar_seconds=settings.CACHE_TTL_HISTORICAL_OPEN_BAR_SECONDS,
        historical_intraday_seconds=settings.CACHE_TTL_HISTORICAL_INTRADAY_SECONDS,
        company_profile_seconds=settings.CACHE_TTL_COMPANY_PROFILE_SECONDS,
        company_search_seconds=settings.CACHE_TTL_COMPANY_SEARCH_SECONDS,
        company_news_seconds=settings.CACHE_TTL_COMPANY_NEWS_SECONDS,
        market_status_seconds=settings.CACHE_TTL_MARKET_STATUS_SECONDS,
        volatility_seconds=settings.CACHE_TTL_VOLATILITY_SECONDS,
        extend_when_market_closed=settings.CACHE_EXTEND_WHEN_MARKET_CLOSED,
    )


def _storage_key(name: str) -> str:
    return (
        "cache_extend_when_market_closed"
        if name == "extend_when_market_closed"
        else f"cache_ttl_{name}"
    )


class CachePolicy:
    def __init__(self) -> None:
        self.values = policy_defaults()
        self._refreshed = float("-inf")
        self._lock = asyncio.Lock()

    async def refresh(self, force: bool = False) -> None:
        if not force and time.monotonic() - self._refreshed < 30:
            return
        try:
            repository = get_settings_repository()
        except RuntimeError:
            return  # Lifespan has not run; no SQLite I/O in hermetic route tests.
        async with self._lock:
            if not force and time.monotonic() - self._refreshed < 30:
                return
            try:
                stored = await repository.get_all()
                values = policy_defaults().model_dump()
                for name in values:
                    raw = stored.get(_storage_key(name))
                    if raw is not None:
                        values[name] = json.loads(raw)
                self.values = CachePolicyValues.model_validate(values)
            except Exception as exc:
                logger.warning("Cache policy refresh failed (%s)", type(exc).__name__)
            self._refreshed = time.monotonic()

    async def update(self, payload: CachePolicyUpdate) -> CachePolicyValues:
        async with self._lock:
            repository = get_settings_repository()
            for name, value in payload.model_dump(exclude_unset=True).items():
                await repository.set(_storage_key(name), json.dumps(value))
            # Reload all fields: don't overwrite another replica's unrelated updates.
            stored = await repository.get_all()
            values = policy_defaults().model_dump()
            for name in values:
                raw = stored.get(_storage_key(name))
                if raw is not None:
                    values[name] = json.loads(raw)
            self.values = CachePolicyValues.model_validate(values)
            self._refreshed = time.monotonic()
            return self.values

    def resolve(
        self, route: str, params: dict[str, str], now: datetime, fallback: int = 300
    ) -> int:
        values = self.values
        now = as_utc(now)
        route = {
            "/companies/{symbol}": "companies:profile",
            "/companies/search": "companies:search",
            "/companies/{symbol}/news": "companies:news",
            "/market-status": "market-status",
            "/volatility/{symbol}": "volatility:snapshot",
            "/volatility/{symbol}/history": "volatility:history",
            "/volatility/{symbol}/stats": "volatility:stats",
        }.get(route, route)
        company_ttls = {
            "companies:profile": values.company_profile_seconds,
            "companies:search": values.company_search_seconds,
            "companies:news": values.company_news_seconds,
        }
        if route in company_ttls:
            return company_ttls[route]
        if route == "market-status":
            until_transition = int((as_utc(next_transition(now)) - now).total_seconds())
            return min(values.market_status_seconds, until_transition)
        if route in {"volatility:snapshot", "volatility:stats"}:
            return values.volatility_seconds
        if route == "volatility:history":
            end = params.get("end")
            if end:
                try:
                    ended = datetime.fromisoformat(end.replace("Z", "+00:00"))
                    # This endpoint accepts dates: midnight is in ET, not UTC.
                    if ended.tzinfo is None:
                        ended = ended.replace(tzinfo=ET)
                    cutoff = current_period_start("1d", now) - timedelta(days=1)
                    if as_utc(ended) < as_utc(cutoff):
                        return values.historical_closed_seconds
                except ValueError:
                    pass  # Endpoint validation still rejects malformed dates.
            return values.volatility_seconds
        extended = params.get("extended_hours", "false").lower() in {
            "true",
            "1",
            "yes",
            "on",
        }
        if route in {"options:chain", "/options/{symbol}/chain"}:
            ttl = values.option_chain_seconds
        elif route in {"prices:history", "/prices/{symbol}/history"}:
            interval = params.get("interval", "1d")
            try:
                length = bar_length_seconds(interval)
                period = current_period_start(interval, now)
            except ValueError:
                return fallback
            end = params.get("end")
            if end:
                try:
                    ended = as_utc(datetime.fromisoformat(end.replace("Z", "+00:00")))
                    cutoff = (
                        datetime.combine(
                            now.astimezone(ET).date(), datetime.min.time(), ET
                        )
                        if length
                        else period - timedelta(days=1)
                    )
                    if ended < as_utc(cutoff):
                        return values.historical_closed_seconds
                except ValueError:
                    pass  # Endpoint validation still governs invalid input.
            ttl = (
                values.historical_intraday_seconds
                if length
                else values.historical_open_bar_seconds
            )
            if length is not None:
                ttl = min(ttl, length)
        else:
            return fallback
        if ttl == 0:
            return 0
        if (
            values.extend_when_market_closed
            and market_state(now, extended) == "settled"
        ):
            until_open = int((as_utc(next_open(now, extended)) - now).total_seconds())
            return min(until_open, values.historical_closed_seconds)
        return ttl


policy = CachePolicy()


def _key_parts(key: str | bytes) -> tuple[str, dict[str, str]]:
    text = key.decode() if isinstance(key, bytes) else key
    segments = text.split(":")
    route = ":".join(segments[1:-2])
    return route, dict(parse_qsl(segments[-1]))


def _compose_key(
    route_key: str, symbol: ParsedSymbol | None, params: dict[str, Any]
) -> str:
    """Compose provider-isolated keys for HTTP and non-HTTP callers.

    The symbol segment is the percent-encoded canonical symbol (no raw ``:``), which
    already encodes the instrument type; `sec_type` is only kept for ETFs.
    """
    params = {
        name: str(value)
        for name, value in params.items()
        if value is not None and value != "" and name != "sec_type"
    }
    if symbol is not None and symbol.sec_type == "etf":
        params["sec_type"] = "etf"
    for name in ("provider", "format"):
        if name in params:
            params[name] = params[name].lower()
    if route_key == "companies:search" and "q" in params:
        params["q"] = " ".join(params["q"].split()).lower()
    if "provider" not in params:
        default = {
            "options:chain": registry.default_options_provider,
            "prices:history": registry.default_price_provider,
            "market-status": registry.default_price_provider,
            "companies:profile": registry.default_company_provider,
            "companies:search": registry.default_company_provider,
            "companies:news": registry.default_news_provider,
            "volatility:snapshot": registry.default_volatility_provider,
            "volatility:history": registry.default_volatility_provider,
            "volatility:stats": registry.default_volatility_provider,
        }.get(route_key)
        if default:
            params["provider"] = default.lower()
    segment = quote(symbol.canonical, safe="") if symbol is not None else ""
    return f"mdh:{route_key}:{segment}:{urlencode(sorted(params.items())) or '-'}"


async def mdh_key_builder(
    func: Any,
    namespace: str = "",
    *,
    request: Request | None = None,
    response: Response | None = None,
    args: Any = None,
    kwargs: Any = None,
) -> str:
    if request is None:
        raise ValueError("MDH cache keys require a request")
    route = request.scope["route"]
    path = namespace.removeprefix("mdh:") or ":".join(
        part for part in route.path.split("/") if part and not part.startswith("{")
    )
    declared = {param.alias for param in route.dependant.query_params}
    params = {
        name: value
        for name, value in request.query_params.items()
        if name in declared and value != ""
    }
    raw_symbol = request.path_params.get("symbol")
    # A malformed symbol raises DataValidationError, so nothing is cached for it.
    symbol = (
        parse_symbol(raw_symbol, request.query_params.get("sec_type"))
        if raw_symbol
        else None
    )
    await policy.refresh()
    return _compose_key(path, symbol, params)


class MdhJsonCoder(JsonCoder):
    @classmethod
    def encode(cls, value: Any) -> bytes:
        if isinstance(value, Response):
            return json.dumps(
                {
                    "_mdh_response": True,
                    "body": base64.b64encode(value.body).decode(),
                    "status": value.status_code,
                    "media_type": value.media_type,
                    "headers": dict(value.headers),
                }
            ).encode()
        return json.dumps(jsonable_encoder(value)).encode()

    @classmethod
    def decode(cls, value: bytes) -> Any:
        decoded = json.loads(value)
        if isinstance(decoded, dict) and decoded.get("_mdh_response") is True:
            return Response(
                base64.b64decode(decoded["body"]),
                status_code=decoded["status"],
                media_type=decoded["media_type"],
                headers=decoded["headers"],
            )
        return decoded


def cache(
    *, expire: int, key: str = ""
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R | Response]]]:
    """Delegate to fastapi-cache2, preserving its headers on concrete CSV Responses."""

    def decorate(
        func: Callable[P, Awaitable[R]],
    ) -> Callable[P, Awaitable[R | Response]]:
        cached = library_cache(expire=expire, namespace=key)(func)

        @wraps(cached)
        async def adapted(*args: P.args, **kwargs: P.kwargs) -> R | Response:
            request = kwargs.get("__fastapi_cache_request")
            token = _request.set(request if isinstance(request, Request) else None)
            try:
                result = await cached(*args, **kwargs)
                injected = kwargs.get("__fastapi_cache_response")
                if (
                    isinstance(result, Response)
                    and isinstance(injected, Response)
                    and result is not injected
                ):
                    for name in ("Cache-Control", "ETag", "X-FastAPI-Cache"):
                        if name in injected.headers:
                            result.headers[name] = injected.headers[name]
                return result
            finally:
                _request.reset(token)

        return adapted

    return decorate


async def cached_call(
    route_key: str,
    symbol: ParsedSymbol | None,
    params: dict[str, Any],
    loader: Callable[[], Awaitable[Any]],
    *,
    refresh: bool = False,
) -> Any:
    """Cache MCP domain data, never exceptions, using the HTTP backend and policy."""
    if not FastAPICache.get_enable():
        return await loader()
    await policy.refresh()
    key = _compose_key(route_key, symbol, {**params, "channel": "mcp"})
    backend = FastAPICache.get_backend()
    if not refresh:
        try:
            value = await backend.get(key)
            if value is not None:
                return MdhJsonCoder.decode(value)
        except Exception as exc:
            logger.warning(
                "MCP cache read failed (%s); serving live data", type(exc).__name__
            )
    result = await loader()
    try:
        await backend.set(key, MdhJsonCoder.encode(result))
    except Exception as exc:
        logger.warning(
            "MCP cache write failed (%s); serving live data", type(exc).__name__
        )
    return result


class FailOpenRedisBackend(RedisBackend):
    def __init__(self, redis: Any) -> None:
        super().__init__(redis)
        self.retry_at = 0.0
        self.unavailable = False

    def failed(self) -> None:
        if not self.unavailable:
            logger.warning(
                "Redis response cache unavailable; serving live data (retry in 30s)"
            )
        self.unavailable = True
        self.retry_at = time.monotonic() + 30

    def recovered(self) -> None:
        if self.unavailable:
            logger.info("Redis response cache recovered")
        self.unavailable = False
        self.retry_at = 0.0

    async def get_with_ttl(self, key: str) -> tuple[int, bytes | None]:
        if time.monotonic() < self.retry_at:
            return 0, None
        try:
            result = await super().get_with_ttl(key)
            self.recovered()
            return result
        except Exception:
            self.failed()
            return 0, None

    async def get(self, key: str) -> bytes | None:
        return (await self.get_with_ttl(key))[1]

    async def set(self, key: str, value: bytes, expire: int | None = None) -> None:
        route, params = _key_parts(key)
        ttl = policy.resolve(route, params, datetime.now(UTC), expire or 300)
        request = _request.get()
        if request is not None:
            request.scope["mdh_cache_ttl"] = ttl
        if ttl == 0 or time.monotonic() < self.retry_at:
            return
        try:
            await super().set(key, value, ttl)
            self.recovered()
        except Exception:
            self.failed()

    async def clear(self, namespace: str | None = None, key: str | None = None) -> int:
        # Never inherit the library's blocking KEYS/Lua clear implementation.
        if key is not None:
            return int(await self.redis.unlink(key)) if key.startswith("mdh:") else 0
        return await clear_cache()


class CacheControlMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def rewrite(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if headers.get("X-FastAPI-Cache") == "MISS":
                    ttl = scope.get("mdh_cache_ttl")
                    if ttl is None:
                        await policy.refresh()
                        route = scope.get("route")
                        params = dict(
                            parse_qsl(scope.get("query_string", b"").decode())
                        )
                        ttl = policy.resolve(
                            getattr(route, "path", ""), params, datetime.now(UTC)
                        )
                    headers["Cache-Control"] = f"max-age={ttl}" if ttl else "no-store"
            await send(message)

        await self.app(scope, receive, rewrite)


_backend: FailOpenRedisBackend | None = None


def redacted_redis_url() -> str:
    parsed = urlsplit(settings.REDIS_URL)
    # Strip all userinfo and query/fragment; these can contain credentials too.
    return urlunsplit(
        (parsed.scheme, parsed.netloc.rsplit("@", 1)[-1], parsed.path, "", "")
    )


def _disable_cache() -> None:
    FastAPICache.reset()
    FastAPICache.init(
        InMemoryBackend(),
        prefix="mdh",
        coder=MdhJsonCoder,
        key_builder=mdh_key_builder,
        enable=False,
    )


_disable_cache()


async def setup_cache() -> str:
    global _backend, policy
    await shutdown_cache()
    policy = CachePolicy()
    await policy.refresh(force=True)
    if not settings.CACHE_ENABLED:
        logger.info("Redis response cache disabled")
        return "disabled"
    redis = aioredis.from_url(
        settings.REDIS_URL,
        socket_connect_timeout=settings.REDIS_TIMEOUT_SECONDS,
        socket_timeout=settings.REDIS_TIMEOUT_SECONDS,
        decode_responses=False,
    )
    _backend = FailOpenRedisBackend(redis)
    FastAPICache.reset()
    FastAPICache.init(
        _backend, prefix="mdh", coder=MdhJsonCoder, key_builder=mdh_key_builder
    )
    try:
        await redis.ping()
        logger.info("Redis response cache connected: %s", redacted_redis_url())
        return "connected"
    except Exception:
        _backend.failed()
        return "unavailable"


async def shutdown_cache() -> None:
    global _backend
    backend, _backend = _backend, None
    _disable_cache()
    if backend is not None:
        try:
            await backend.redis.close()
            await backend.redis.connection_pool.disconnect()
        except Exception:
            logger.warning("Redis response cache pool close failed")


async def cache_status() -> dict[str, Any]:
    await policy.refresh()
    now = datetime.now(UTC)
    result: dict[str, Any] = {
        "state": "disabled" if _backend is None else "unavailable",
        "redis_url": redacted_redis_url(),
        "policy": policy.values.model_dump(),
        "defaults": policy_defaults().model_dump(),
        "market": {"state": market_state(now), "next_open": next_open(now).isoformat()},
        "memory": None,
        "key_counts": None,
    }
    if _backend is None or time.monotonic() < _backend.retry_at:
        return result
    try:
        memory = await _backend.redis.info("memory")
        counts = {}
        for name, pattern in _PATTERNS.items():
            if name == "all":
                continue
            counts[name] = 0
            async for _ in _backend.redis.scan_iter(match=pattern, count=500):
                counts[name] += 1
        _backend.recovered()
        result.update(
            state="connected",
            memory={
                "used_memory": memory["used_memory"],
                "maxmemory": memory["maxmemory"],
            },
            key_counts=counts,
        )
    except Exception:
        _backend.failed()
    return result


async def clear_cache(scope: CacheScope = "all", provider: str | None = None) -> int:
    if _backend is None or time.monotonic() < _backend.retry_at:
        raise RuntimeError("Redis response cache is disabled or unavailable")
    deleted = 0
    batch = []
    try:
        async for key in _backend.redis.scan_iter(match=_PATTERNS[scope], count=500):
            if provider and _key_parts(key)[1].get("provider") != provider.lower():
                continue
            batch.append(key)
            if len(batch) == 500:
                deleted += int(await _backend.redis.unlink(*batch))
                batch.clear()
        if batch:
            deleted += int(await _backend.redis.unlink(*batch))
        _backend.recovered()
    except Exception as exc:
        _backend.failed()
        raise RuntimeError("Redis response cache is unavailable") from exc
    return deleted
