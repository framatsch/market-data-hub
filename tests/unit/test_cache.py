from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from fastapi_cache import FastAPICache
from pydantic import ValidationError

from app import cache as response_cache
from app.admin.runtime import set_admin_runtime
from app.admin.settings_repository import SettingsRepository
from app.api import routes_options, routes_prices
from app.config import settings
from app.dependencies import get_options_service, get_price_service
from app.market_hours import ET, as_utc, next_open
from app.models.options import OptionChain, OptionQuote

NOW = datetime(2026, 11, 4, 11, tzinfo=ET)


@pytest.fixture
def policy(monkeypatch):
    monkeypatch.setattr(response_cache, "policy", response_cache.CachePolicy())
    return response_cache.policy


@pytest.mark.parametrize(
    "route,params,ttl",
    [
        ("options:chain", {}, 900),
        ("volatility:snapshot", {}, 900),
        ("volatility:stats", {}, 900),
        ("volatility:history", {}, 900),
        ("volatility:history", {"end": "2026-11-02"}, 604800),
        ("volatility:history", {"end": "2026-11-03"}, 900),
        ("volatility:history", {"end": "invalid"}, 900),
        ("prices:history", {}, 300),
        ("prices:history", {"interval": "5m"}, 300),
        ("prices:history", {"interval": "1m"}, 60),
        ("prices:history", {"interval": "1h"}, 300),
        ("prices:history", {"interval": "1mo"}, 300),
        ("prices:history", {"interval": "1w", "end": "2025-12-31"}, 604800),
        (
            "prices:history",
            {"interval": "5m", "end": "2026-11-03T16:00:00-05:00"},
            604800,
        ),
        ("prices:history", {"interval": "1d", "end": "2026-11-03T16:00:00-05:00"}, 300),
        (
            "prices:history",
            {"interval": "1d", "end": "2026-11-02T16:00:00-05:00"},
            604800,
        ),
        (
            "prices:history",
            {"interval": "1w", "end": "2026-10-31T16:00:00-04:00"},
            604800,
        ),
        (
            "prices:history",
            {"interval": "1mo", "end": "2026-10-30T16:00:00-04:00"},
            604800,
        ),
        ("prices:history", {"interval": "1m", "end": "2026-11-04T04:59:00"}, 604800),
        ("prices:history", {"interval": "1m", "end": "2026-11-04T05:00:00"}, 60),
    ],
)
def test_policy_session_and_closed_range(policy, route, params, ttl):
    assert policy.resolve(route, params, NOW) == ttl


@pytest.mark.parametrize(
    "route,params",
    [
        ("options:chain", {}),
        ("prices:history", {"interval": "1m"}),
        ("prices:history", {"interval": "1d"}),
    ],
)
def test_policy_extension(policy, route, params):
    weekend = datetime(2026, 11, 7, 10, tzinfo=ET)
    expected = int((as_utc(next_open(weekend)) - as_utc(weekend)).total_seconds())
    assert policy.resolve(route, params, weekend) == expected
    policy.values.historical_closed_seconds = 123
    assert policy.resolve(route, params, weekend) == 123


def test_policy_extension_off_extended_hours_and_zero(policy):
    evening = datetime(2026, 11, 4, 18, tzinfo=ET)
    assert (
        policy.resolve(
            "prices:history", {"interval": "5m", "extended_hours": "true"}, evening
        )
        == 300
    )
    policy.values.extend_when_market_closed = False
    assert policy.resolve("prices:history", {}, evening) == 300
    assert policy.resolve("options:chain", {}, evening) == 900
    policy.values.extend_when_market_closed = True
    policy.values.option_chain_seconds = 0
    policy.values.historical_intraday_seconds = 0
    assert policy.resolve("options:chain", {}, evening) == 0
    assert policy.resolve("prices:history", {"interval": "1m"}, evening) == 0
    assert policy.resolve("unknown", {}, NOW, 42) == 42


@pytest.mark.parametrize(
    "payload",
    [
        {"option_chain_seconds": -1},
        {"historical_closed_seconds": 2592001},
        {"historical_intraday_seconds": 1.5},
        {"historical_open_bar_seconds": True},
        {"option_chain_seconds": None},
        {"extend_when_market_closed": "false"},
    ],
)
def test_policy_validation(payload):
    with pytest.raises(ValidationError):
        response_cache.CachePolicyUpdate.model_validate(payload)


async def test_policy_env_stored_refresh_and_partial_update(
    policy, monkeypatch, tmp_path
):
    monkeypatch.setattr(settings, "CACHE_TTL_OPTION_CHAIN_SECONDS", 120)
    repository = SettingsRepository(str(tmp_path / "keys.db"))
    set_admin_runtime(settings_repository=repository)
    try:
        await policy.refresh(force=True)
        assert policy.values.option_chain_seconds == 120
        await repository.set("cache_ttl_option_chain_seconds", "240")
        await policy.refresh()
        assert policy.values.option_chain_seconds == 120  # 30s refresh window
        policy._refreshed -= 31
        await policy.refresh()
        assert policy.values.option_chain_seconds == 240
        values = await policy.update(
            response_cache.CachePolicyUpdate(historical_intraday_seconds=0)
        )
        assert values.option_chain_seconds == 240
        assert values.historical_intraday_seconds == 0
        assert await repository.get("cache_ttl_historical_intraday_seconds") == "0"
    finally:
        set_admin_runtime()


@pytest.mark.parametrize("route", ["volatility:snapshot", "volatility:history", "volatility:stats"])
@pytest.mark.parametrize("now", [datetime(2026, 11, 4, 16, 35, tzinfo=ET), datetime(2026, 11, 7, 10, tzinfo=ET)])
def test_volatility_never_extends_after_close(policy, route, now):
    assert policy.resolve(route, {}, now) == 900
    policy.values.volatility_seconds = 0
    assert policy.resolve(route, {}, now) == 0
    if route == "volatility:history":
        assert policy.resolve(route, {"end": "2025-12-31"}, now) == 604800


async def test_volatility_policy_env_and_runtime_override(policy, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "CACHE_TTL_VOLATILITY_SECONDS", 3600)
    repository = SettingsRepository(str(tmp_path / "keys.db"))
    set_admin_runtime(settings_repository=repository)
    try:
        await policy.refresh(force=True)
        assert policy.values.volatility_seconds == 3600
        updated = await policy.update(response_cache.CachePolicyUpdate(volatility_seconds=0))
        assert updated.volatility_seconds == 0
        assert await repository.get("cache_ttl_volatility_seconds") == "0"
    finally:
        set_admin_runtime()


@pytest.mark.parametrize("route", ["volatility:snapshot", "volatility:history", "volatility:stats"])
async def test_volatility_implicit_provider_key(policy, monkeypatch, route):
    monkeypatch.setattr(response_cache.registry, "default_volatility_provider", "lseg")
    request = Request({
        "type": "http", "route": SimpleNamespace(path="/unused", dependant=SimpleNamespace(query_params=[])),
        "path_params": {"symbol": "aapl"}, "query_string": b"",
    })
    assert await response_cache.mdh_key_builder(None, f"mdh:{route}", request=request) == f"mdh:{route}:AAPL:provider=lseg"


@pytest.mark.parametrize(
    "path,query,expected",
    [
        (
            "/options/{symbol}/chain",
            "provider=Schwab",
            "mdh:options:chain:SPX:provider=schwab",
        ),
        (
            "/prices/{symbol}/history",
            "provider=Schwab&interval=1d",
            "mdh:prices:history:SPX:interval=1d&provider=schwab",
        ),
        (
            "/prices/{symbol}/history",
            "interval=1d&provider=Schwab&_ts=1",
            "mdh:prices:history:SPX:interval=1d&provider=schwab",
        ),
        (
            "/options/{symbol}/chain",
            "provider=Schwab&format=CSV&sec_type=INDEX",
            "mdh:options:chain:I%3ASPX:format=csv&provider=schwab",
        ),
        (
            "/options/{symbol}/chain",
            "provider=Schwab&sec_type=etf",
            "mdh:options:chain:SPX:provider=schwab&sec_type=etf",
        ),
        (
            "/options/{symbol}/chain",
            "provider=Schwab&sec_type=STK",
            "mdh:options:chain:SPX:provider=schwab",
        ),
        (
            "/prices/{symbol}/history",
            "start=2026-01-01T00%3A00%3A00&provider=schwab",
            "mdh:prices:history:SPX:provider=schwab&start=2026-01-01T00%3A00%3A00",
        ),
        ("/other/{symbol}", "_ts=1&format=", "mdh:other:SPX:-"),
    ],
)
async def test_key_builder(policy, path, query, expected):
    route = SimpleNamespace(
        path=path,
        dependant=SimpleNamespace(
            query_params=[
                SimpleNamespace(alias=name)
                for name in ("provider", "format", "sec_type", "interval", "start")
            ]
        ),
    )
    request = Request(
        {
            "type": "http",
            "route": route,
            "path_params": {"symbol": "spx"},
            "query_string": query.encode(),
        }
    )
    assert (
        await response_cache.mdh_key_builder(None, "mdh:", request=request) == expected
    )


def _symbol_request(path, symbol, query=""):
    route = SimpleNamespace(
        path=path,
        dependant=SimpleNamespace(
            query_params=[SimpleNamespace(alias="provider")]
        ),
    )
    return Request(
        {
            "type": "http",
            "route": route,
            "path_params": {"symbol": symbol},
            "query_string": query.encode(),
        }
    )


@pytest.mark.parametrize(
    "symbol,query",
    [
        ("F:ES", "provider=lseg"),
        ("f:es", "provider=lseg"),
        ("/ES", "provider=lseg"),
        ("ES", "provider=lseg&sec_type=future"),
        ("ES", "provider=lseg&sec_type=FUTURE"),
    ],
)
async def test_namespaced_and_legacy_requests_share_key(policy, symbol, query):
    request = _symbol_request("/volatility/{symbol}/stats", symbol, query)
    key = await response_cache.mdh_key_builder(
        None, "mdh:volatility:stats", request=request
    )
    assert key == "mdh:volatility:stats:F%3AES:provider=lseg"


async def test_alias_and_prefix_share_key(policy):
    keys = {
        await response_cache.mdh_key_builder(
            None,
            "mdh:",
            request=_symbol_request(
                "/prices/{symbol}/history", symbol, "provider=ibkr"
            ),
        )
        for symbol in ("^SPX", "I:SPX", "i:spx")
    }
    assert keys == {"mdh:prices:history:I%3ASPX:provider=ibkr"}


async def test_etf_key_keeps_sec_type(policy):
    request = _symbol_request(
        "/volatility/{symbol}", "SPY", "provider=lseg&sec_type=etf"
    )
    key = await response_cache.mdh_key_builder(
        None, "mdh:volatility:snapshot", request=request
    )
    assert key == "mdh:volatility:snapshot:SPY:provider=lseg&sec_type=etf"


async def test_invalid_symbol_in_key_builder_raises(policy):
    from app.utils.errors import DataValidationError

    for symbol, query in (("F:ES", "sec_type=stock"), (".SPX", ""), ("X:Y", "")):
        with pytest.raises(DataValidationError):
            await response_cache.mdh_key_builder(
                None, "mdh:", request=_symbol_request("/prices/{symbol}/last", symbol, query)
            )


@pytest.mark.parametrize(
    "key,route",
    [
        ("mdh:prices:history:I%3ASPX:interval=1d&provider=ibkr", "prices:history"),
        ("mdh:volatility:stats:F%3AES:provider=lseg", "volatility:stats"),
    ],
)
def test_key_parts_derives_route_for_namespaced_symbol(key, route):
    derived, params = response_cache._key_parts(key)
    assert derived == route
    assert params["provider"] in {"ibkr", "lseg"}


def test_compose_key_without_symbol(policy):
    assert (
        response_cache._compose_key("market-status", None, {"provider": "Polygon"})
        == "mdh:market-status::provider=polygon"
    )


async def test_implicit_default_provider(policy, monkeypatch):
    route = SimpleNamespace(
        path="/options/{symbol}/chain",
        dependant=SimpleNamespace(query_params=[SimpleNamespace(alias="provider")]),
    )
    request = Request(
        {
            "type": "http",
            "route": route,
            "path_params": {"symbol": "spx"},
            "query_string": b"",
        }
    )
    monkeypatch.setattr(response_cache.registry, "default_options_provider", "schwab")
    assert (
        await response_cache.mdh_key_builder(None, "mdh:", request=request)
        == "mdh:options:chain:SPX:provider=schwab"
    )
    monkeypatch.setattr(response_cache.registry, "default_options_provider", "ibkr")
    assert (
        await response_cache.mdh_key_builder(None, "mdh:", request=request)
    ).endswith("provider=ibkr")
    monkeypatch.setattr(response_cache.registry, "default_options_provider", None)
    assert (
        await response_cache.mdh_key_builder(None, "mdh:", request=request)
    ).endswith(":-")


@pytest.fixture
def route_client(cache_redis):
    app = FastAPI()
    app.add_middleware(response_cache.CacheControlMiddleware)
    app.include_router(routes_prices.router)
    app.include_router(routes_options.router)
    quote = OptionQuote(
        symbol="AAPL-call",
        underlying_symbol="AAPL",
        strike=Decimal("123.45"),
        expiry=date(2026, 12, 18),
        type="call",
        price=Decimal("1.50"),
        provider="schwab",
    )
    options = SimpleNamespace(
        get_option_chain=AsyncMock(
            return_value=OptionChain(
                underlying_symbol="AAPL",
                expiry=quote.expiry,
                options=[quote],
                provider="schwab",
            )
        )
    )
    prices = SimpleNamespace(
        get_historical_prices=AsyncMock(
            return_value=[{"symbol": "AAPL", "close": "123.45"}]
        )
    )
    app.dependency_overrides[get_price_service] = lambda: prices
    app.dependency_overrides[get_options_service] = lambda: options
    response_cache.policy.values.extend_when_market_closed = False
    yield TestClient(app), options, prices


@pytest.mark.parametrize(
    "path,service",
    [("/options/AAPL/chain", "options"), ("/prices/AAPL/history", "prices")],
)
@pytest.mark.parametrize("format", ["json", "csv"])
def test_json_csv_hit_miss(route_client, cache_redis, path, service, format):
    client, options, prices = route_client
    response_cache.policy.values.option_chain_seconds = 123
    response_cache.policy.values.historical_open_bar_seconds = 123
    url = f"{path}?provider=Schwab&format={format}"
    first = client.get(url)
    second = client.get(url)
    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    assert first.headers["x-fastapi-cache"] == "MISS"
    assert second.headers["x-fastapi-cache"] == "HIT"
    assert (
        first.headers["cache-control"]
        == second.headers["cache-control"]
        == "max-age=123"
    )
    assert set(cache_redis.ttls.values()) == {123}
    call = (
        options.get_option_chain
        if service == "options"
        else prices.get_historical_prices
    )
    assert call.await_count == 1
    if format == "csv":
        assert first.headers["content-type"].startswith("text/csv")
        assert (
            first.headers["content-disposition"]
            == second.headers["content-disposition"]
        )
    elif service == "options":
        assert first.json()["data"]["options"][0]["price"] == "1.50"
    conditional = client.get(url, headers={"If-None-Match": second.headers["etag"]})
    assert conditional.status_code == 304


def test_bypass_headers(route_client):
    client, options, _ = route_client
    url = "/options/AAPL/chain?provider=schwab"
    client.get(url)
    assert (
        client.get(url, headers={"Cache-Control": "no-cache"}).headers[
            "x-fastapi-cache"
        ]
        == "MISS"
    )
    no_store = client.get(url, headers={"Cache-Control": "no-store"})
    assert "x-fastapi-cache" not in no_store.headers
    assert client.get(url).headers["x-fastapi-cache"] == "HIT"
    assert options.get_option_chain.await_count == 3


def test_errors_not_cached(route_client, cache_redis):
    client, options, _ = route_client
    options.get_option_chain.side_effect = HTTPException(
        status_code=503, detail="Provider unavailable"
    )
    for _ in range(2):
        assert client.get("/options/AAPL/chain?provider=schwab").status_code == 503
    assert options.get_option_chain.await_count == 2
    assert not cache_redis.entries
    assert client.get("/options/AAPL/chain?min_strike=invalid").status_code == 422
    assert not cache_redis.entries


def test_not_entitled_not_cached_so_upgrade_takes_effect(route_client, cache_redis):
    from fastapi.responses import JSONResponse

    from app.utils.errors import AppError, ProviderNotEntitledError

    client, options, _ = route_client
    client.app.add_exception_handler(
        AppError,
        lambda _request, exc: JSONResponse(
            {"error": {"code": exc.code}}, status_code=403
        ),
    )
    chain = options.get_option_chain.return_value
    options.get_option_chain.side_effect = [
        ProviderNotEntitledError("schwab", symbol="I:SPX"),
        ProviderNotEntitledError("schwab", symbol="I:SPX"),
        chain,
    ]
    url = "/options/AAPL/chain?provider=schwab"
    for _ in range(2):
        denied = client.get(url)
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "PROVIDER_NOT_ENTITLED"
    assert not cache_redis.entries
    upgraded = client.get(url)
    assert upgraded.status_code == 200
    assert upgraded.headers["x-fastapi-cache"] == "MISS"
    assert options.get_option_chain.await_count == 3


def test_effective_provider_keys_share_then_switch(route_client, monkeypatch):
    client, options, _ = route_client
    monkeypatch.setattr(response_cache.registry, "default_options_provider", "schwab")
    assert client.get("/options/aapl/chain").headers["x-fastapi-cache"] == "MISS"
    assert (
        client.get("/options/AAPL/chain?provider=Schwab&_ts=123").headers[
            "x-fastapi-cache"
        ]
        == "HIT"
    )
    monkeypatch.setattr(response_cache.registry, "default_options_provider", "ibkr")
    assert client.get("/options/AAPL/chain").headers["x-fastapi-cache"] == "MISS"
    assert options.get_option_chain.await_count == 2


def test_write_failure_is_fail_open(route_client, cache_redis, monkeypatch, caplog):
    client, options, _ = route_client
    caplog.set_level("INFO")
    original_set = cache_redis.set
    monkeypatch.setattr(
        cache_redis, "set", AsyncMock(side_effect=ConnectionError("offline"))
    )
    assert client.get("/options/AAPL/chain?provider=schwab").status_code == 200
    calls = cache_redis.calls
    assert client.get("/options/AAPL/chain?provider=schwab").status_code == 200
    assert cache_redis.calls == calls
    monkeypatch.setattr(cache_redis, "set", original_set)
    response_cache._backend.retry_at = 0
    assert (
        client.get("/options/AAPL/chain?provider=schwab").headers["x-fastapi-cache"]
        == "MISS"
    )
    assert "Redis response cache recovered" in caplog.text
    assert options.get_option_chain.await_count == 3


def test_zero_policy_no_write_and_no_store_header(route_client, cache_redis):
    client, options, _ = route_client
    response_cache.policy.values.option_chain_seconds = 0
    for _ in range(2):
        assert (
            client.get("/options/AAPL/chain?provider=schwab").headers["cache-control"]
            == "no-store"
        )
    assert options.get_option_chain.await_count == 2
    assert not cache_redis.entries


def test_fail_open_cooldown_and_recovery(
    route_client, cache_redis, monkeypatch, caplog
):
    client, options, _ = route_client
    clock = [100.0]
    monkeypatch.setattr(response_cache.time, "monotonic", lambda: clock[0])
    cache_redis.fail = True
    url = "/options/AAPL/chain?provider=schwab"
    assert client.get(url).status_code == 200
    calls = cache_redis.calls
    assert client.get(url).status_code == 200
    assert cache_redis.calls == calls
    assert sum("cache unavailable" in record.message for record in caplog.records) == 1
    clock[0] += 31
    cache_redis.fail = False
    assert client.get(url).headers["x-fastapi-cache"] == "MISS"
    assert client.get(url).headers["x-fastapi-cache"] == "HIT"
    assert options.get_option_chain.await_count == 3


async def test_lifecycle_with_redis_down(cache_redis, monkeypatch):
    # Release the fixture's fake backend, then exercise real setup with a failing fake client.
    monkeypatch.setattr(settings, "CACHE_ENABLED", True)
    monkeypatch.setattr(
        response_cache.aioredis, "from_url", lambda *args, **kwargs: cache_redis
    )
    cache_redis.fail = True
    assert await response_cache.setup_cache() == "unavailable"
    assert FastAPICache.get_enable()
    assert (await response_cache.cache_status())["state"] == "unavailable"
    await response_cache.shutdown_cache()
    assert not FastAPICache.get_enable()
    assert cache_redis.close.await_count >= 1
    cache_redis.connection_pool.disconnect.assert_awaited()


async def test_disabled_lifecycle_does_not_connect(monkeypatch):
    monkeypatch.setattr(settings, "CACHE_ENABLED", False)
    connect = AsyncMock()
    monkeypatch.setattr(response_cache.aioredis, "from_url", connect)
    assert await response_cache.setup_cache() == "disabled"
    connect.assert_not_called()
    await response_cache.shutdown_cache()


async def test_application_lifespan_redis_down(cache_redis, monkeypatch, capsys):
    from app.main import app, lifespan

    monkeypatch.setattr(settings, "CACHE_ENABLED", True)
    monkeypatch.setattr("app.admin.runtime.initialize_admin_runtime", lambda: None)
    monkeypatch.setattr(response_cache.registry, "reload_from_config", AsyncMock())
    monkeypatch.setattr(response_cache.registry, "shutdown", AsyncMock())
    monkeypatch.setattr(
        response_cache.aioredis, "from_url", lambda *args, **kwargs: cache_redis
    )
    cache_redis.fail = True
    async with lifespan(app):
        assert (await response_cache.cache_status())["state"] == "unavailable"
        assert "Cache Status: unavailable" in capsys.readouterr().out
    assert not FastAPICache.get_enable()


def test_disabled_endpoints_without_lifespan(route_client):
    client, options, _ = route_client
    response_cache._disable_cache()
    for _ in range(2):
        result = client.get("/options/AAPL/chain?provider=schwab")
        assert result.status_code == 200
        assert "x-fastapi-cache" not in result.headers
    assert options.get_option_chain.await_count == 2


def test_redacted_url(monkeypatch):
    monkeypatch.setattr(
        settings, "REDIS_URL", "redis://user:secret@redis:6379/2?token=secret#secret"
    )
    assert response_cache.redacted_redis_url() == "redis://redis:6379/2"
