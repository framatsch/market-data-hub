"""Coverage for company/meta HTTP and MCP response-cache integration."""

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app import cache as response_cache
from app.api import mcp, routes_companies, routes_meta, routes_prices, routes_volatility
from app.dependencies import (
    get_company_service,
    get_news_service,
    get_price_service,
    get_volatility_service,
)
from app.market_hours import ET
from app.models.common import MarketStatus
from app.models.company import CompanyProfile, CompanySummary
from app.models.news import NewsArticle
from app.models.options import OptionChain
from app.utils.errors import AppError
from app.utils.symbols import parse_symbol

NOW = datetime(2026, 11, 4, 11, tzinfo=ET)
ROUTES = {
    "companies:profile": ("company_profile_seconds", 86400),
    "companies:search": ("company_search_seconds", 3600),
    "companies:news": ("company_news_seconds", 600),
    "market-status": ("market_status_seconds", 60),
}


@pytest.fixture
def services(monkeypatch):
    company = SimpleNamespace(
        get_company_profile=AsyncMock(return_value=CompanyProfile(
            symbol="AAPL", name="Apple", exchange="NASDAQ", currency="USD", provider="finnhub",
        )),
        search_companies=AsyncMock(return_value=[CompanySummary(
            symbol="AAPL", name="Apple", exchange="NASDAQ", provider="finnhub",
        )]),
    )
    news = SimpleNamespace(
        registry=response_cache.registry,
        get_company_news=AsyncMock(return_value=[NewsArticle(
            article_id="finnhub:1", title="News", summary="Summary", published_at=NOW,
            source="Test", url="https://example.com/news",
        )]),
    )
    prices = SimpleNamespace(
        get_market_status=AsyncMock(return_value=MarketStatus(
            market="open", server_time=NOW, provider="polygon",
        )),
        get_historical_prices=AsyncMock(return_value=[]),
        get_latest_price=AsyncMock(return_value=None),
    )
    options = SimpleNamespace(
        get_option_chain=AsyncMock(return_value=OptionChain(
            underlying_symbol="AAPL", expiry=NOW.date(), options=[], provider="schwab",
        )),
        get_option_quote=AsyncMock(return_value=CompanySummary(
            symbol="AAPL", name="Apple", exchange="NASDAQ", provider="test",
        )),
    )
    monkeypatch.setattr(mcp, "_company_service", lambda: company)
    monkeypatch.setattr(mcp, "_price_service", lambda: prices)
    monkeypatch.setattr(mcp, "_options_service", lambda: options)
    monkeypatch.setattr(mcp, "_news_service", lambda: news)
    return company, news, prices, options


@pytest.fixture
def client(cache_redis, services):
    company, news, prices, _ = services
    app = FastAPI()
    app.add_middleware(response_cache.CacheControlMiddleware)
    for router in (routes_companies.router, routes_meta.router, routes_prices.router):
        app.include_router(router)
    app.dependency_overrides[get_company_service] = lambda: company
    app.dependency_overrides[get_news_service] = lambda: news
    app.dependency_overrides[get_price_service] = lambda: prices
    return TestClient(app)


@pytest.mark.parametrize("url,index,method,ttl", [
    ("/companies/AAPL?provider=finnhub", 0, "get_company_profile", 86400),
    ("/companies/search?q=Apple&provider=finnhub", 0, "search_companies", 3600),
    ("/companies/AAPL/news?provider=finnhub&days=7", 1, "get_company_news", 600),
    ("/companies/AAPL/news?provider=finnhub&format=csv", 1, "get_company_news", 600),
    ("/market-status?provider=polygon", 2, "get_market_status", 60),
])
def test_http_hit_body_and_provider_call(client, cache_redis, services, url, index, method, ttl):
    first, second = client.get(url), client.get(url)
    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    assert first.headers["x-fastapi-cache"] == "MISS"
    assert second.headers["x-fastapi-cache"] == "HIT"
    assert getattr(services[index], method).await_count == 1
    assert 0 < next(iter(cache_redis.ttls.values())) <= ttl
    if "csv" in url:
        assert first.headers["content-type"].startswith("text/csv")
        assert first.headers["content-disposition"] == second.headers["content-disposition"]
    else:
        assert "data" in second.json()


def test_search_normalization_empty_results_and_news_pagination(client, services):
    services[0].search_companies.return_value = []
    first = client.get("/companies/search", params={"q": "  Apple  Inc  ", "provider": "finnhub"})
    second = client.get("/companies/search", params={"q": "apple inc", "provider": "finnhub", "channel": "mcp"})
    assert first.json()["data"] == second.json()["data"] == []
    assert second.headers["x-fastapi-cache"] == "HIT"
    services[0].search_companies.assert_awaited_once_with("  Apple  Inc  ", "finnhub")
    for offset in (0, 20):
        assert client.get(f"/companies/AAPL/news?provider=finnhub&offset={offset}").status_code == 200
    assert services[1].get_company_news.await_count == 2


@pytest.mark.parametrize("route,capability,symbol,query", [
    ("companies:profile", "company", "aapl", "provider=Finnhub&channel=mcp"),
    ("companies:search", "company", "", "q=+Apple++Inc+&channel=mcp"),
    ("companies:news", "news", "aapl", ""),
    ("market-status", "price", "", ""),
    ("options:chain", "options", "spx", ""),
    ("prices:history", "price", "aapl", ""),
])
async def test_explicit_keys_and_capability_defaults(cache_redis, monkeypatch, route, capability, symbol, query):
    monkeypatch.setattr(response_cache.registry, f"default_{capability}_provider", "finnhub")
    request = Request({
        "type": "http", "route": SimpleNamespace(path="/wrong", dependant=SimpleNamespace(
            query_params=[SimpleNamespace(alias="provider"), SimpleNamespace(alias="q")],
        )), "path_params": {"symbol": symbol}, "query_string": query.encode(),
    })
    key = await response_cache.mdh_key_builder(None, f"mdh:{route}", request=request)
    expected = f"mdh:{route}:{symbol.upper()}:provider=finnhub"
    if route == "companies:search":
        expected += "&q=apple+inc"
    assert key == expected


@pytest.mark.parametrize("route", ROUTES)
def test_new_policy_ttls_zero_and_no_extension(cache_redis, route):
    field, ttl = ROUTES[route]
    policy = response_cache.policy
    assert policy.resolve(route, {}, NOW) == ttl
    assert policy.resolve(route, {}, datetime(2026, 11, 7, 10, tzinfo=ET)) == ttl
    setattr(policy.values, field, 0)
    assert policy.resolve(route, {}, NOW) == 0


def test_market_status_transition_cap(cache_redis):
    policy = response_cache.policy
    assert policy.resolve("market-status", {}, NOW.replace(hour=9, minute=29, second=30)) == 30
    assert policy.resolve("market-status", {}, NOW.replace(hour=9, minute=29, second=59, microsecond=500000)) == 0


TOOLS = [
    ("get_historical_prices", {"symbol": "aapl", "start_date": "2026-01-01", "end_date": "2026-01-02"}, 2, "get_historical_prices", "prices:history"),
    ("get_option_chain", {"symbol": "aapl", "expiry": "2026-12-18"}, 3, "get_option_chain", "options:chain"),
    ("get_company_profile", {"symbol": "aapl"}, 0, "get_company_profile", "companies:profile"),
    ("search_companies", {"query": "Apple"}, 0, "search_companies", "companies:search"),
    ("get_company_news", {"symbol": "aapl", "from_date": "2026-01-01"}, 1, "get_company_news", "companies:news"),
    ("get_market_status", {}, 2, "get_market_status", "market-status"),
]


@pytest.mark.parametrize("name,args,index,method,route", TOOLS)
async def test_mcp_cached_tools_hit_refresh_schema_and_keys(cache_redis, services, name, args, index, method, route):
    args = {**args, "provider": "test"}
    handler = mcp.TOOL_HANDLERS[name]
    first, second = await handler(args), await handler(args)
    assert first == second
    call = getattr(services[index], method)
    assert call.await_count == 1
    key = next(iter(cache_redis.entries))
    assert key.startswith(f"mdh:{route}:") and "channel=mcp" in key
    assert "start_date=" not in key and "end_date=" not in key and "query=" not in key
    if "start_date" in args:
        assert "start=2026-01-01" in key and "end=2026-01-02" in key
    if "query" in args:
        assert "q=apple" in key
    await handler({**args, "refresh": True})
    assert call.await_count == 2
    await handler(args)
    assert call.await_count == 2
    schema = next(tool for tool in mcp.TOOL_REGISTRY if tool["name"] == name)
    assert schema["inputSchema"]["properties"]["refresh"]["type"] == "boolean"


async def test_mcp_helper_refresh_overwrites_and_isolates_http(cache_redis, client):
    loader = AsyncMock(return_value={"name": "first"})
    params = {"provider": "finnhub"}
    aapl = parse_symbol("aapl")
    await response_cache.cached_call("companies:profile", aapl, params, loader)
    assert client.get("/companies/AAPL?provider=finnhub&channel=mcp").headers["x-fastapi-cache"] == "MISS"
    loader.return_value = {"name": "new"}
    await response_cache.cached_call("companies:profile", aapl, params, loader, refresh=True)
    assert await response_cache.cached_call("companies:profile", aapl, params, loader) == {"name": "new"}
    assert loader.await_count == 2


@pytest.mark.parametrize("mode", ["offline", "write_failure", "error", "disabled", "zero"])
async def test_mcp_live_on_failure_disabled_or_zero(cache_redis, monkeypatch, services, mode):
    call = services[0].get_company_profile
    if mode == "offline":
        cache_redis.fail = True
    elif mode == "write_failure":
        monkeypatch.setattr(cache_redis, "set", AsyncMock(side_effect=ConnectionError()))
    elif mode == "error":
        call.side_effect = ValueError("provider error")
    elif mode == "disabled":
        response_cache._disable_cache()
    else:
        response_cache.policy.values.company_profile_seconds = 0
    for _ in range(2):
        if mode == "error":
            with pytest.raises(ValueError, match="provider error"):
                await mcp._tool_get_company_profile({"symbol": "aapl"})
        else:
            result = await mcp._tool_get_company_profile({"symbol": "aapl"})
            assert json.loads(result["content"][0]["text"])["symbol"] == "AAPL"
    assert call.await_count == 2
    assert not cache_redis.entries


@pytest.mark.parametrize("url", ["/prices/AAPL/last", "/providers", "/health", "/metrics"])
def test_never_cached_http(client, cache_redis, url):
    for _ in range(2):
        response = client.get(url)
        assert "x-fastapi-cache" not in response.headers
        assert "cache-control" not in response.headers
    assert not cache_redis.entries


@pytest.mark.parametrize("name,method,index", [("get_last_price", "get_latest_price", 2), ("get_option_quote", "get_option_quote", 3)])
async def test_never_cached_mcp(cache_redis, services, name, method, index):
    for _ in range(2):
        await mcp.TOOL_HANDLERS[name]({"symbol": "aapl", "option_id": "option"})
    assert getattr(services[index], method).await_count == 2
    assert not cache_redis.entries
    schema = next(tool for tool in mcp.TOOL_REGISTRY if tool["name"] == name)
    assert "refresh" not in schema["inputSchema"]["properties"]


@pytest.fixture
def volatility_cache_client(cache_redis, volatility_env, monkeypatch):
    from app.main import app_error_handler

    monkeypatch.setattr(response_cache, "registry", volatility_env.registry)
    monkeypatch.setattr(mcp, "_volatility_service", lambda: volatility_env.service)
    app = FastAPI()
    app.add_middleware(response_cache.CacheControlMiddleware)
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(routes_volatility.router)
    app.dependency_overrides[get_volatility_service] = lambda: volatility_env.service
    return TestClient(app)


@pytest.mark.parametrize("suffix,method", [("", "get_implied_volatility"), ("/history", "get_implied_volatility_history"), ("/stats", "get_implied_volatility_history")])
@pytest.mark.parametrize("format", ["json", "csv"])
def test_volatility_http_cache(volatility_cache_client, cache_redis, volatility_env, suffix, method, format):
    url = f"/volatility/AAPL{suffix}?format={format}"
    first, second = volatility_cache_client.get(url), volatility_cache_client.get(url)
    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    assert first.headers["x-fastapi-cache"] == "MISS" and second.headers["x-fastapi-cache"] == "HIT"
    assert first.headers["cache-control"] == "max-age=900"
    assert getattr(volatility_env.lseg, method).await_count == 1
    assert set(cache_redis.ttls.values()) == {900}


def test_volatility_cache_keys_isolate_ric_window_and_provider(volatility_cache_client, cache_redis, volatility_env):
    assert volatility_cache_client.get("/volatility/AAPL").headers["x-fastapi-cache"] == "MISS"
    assert volatility_cache_client.get("/volatility/AAPL?provider=lseg").headers["x-fastapi-cache"] == "HIT"
    assert volatility_cache_client.get("/volatility/AAPL?ric=AAPLATMIV.U").headers["x-fastapi-cache"] == "MISS"
    volatility_env.registry.default_volatility_provider = "ibkr"
    assert volatility_cache_client.get("/volatility/AAPL").headers["x-fastapi-cache"] == "MISS"
    for window in (20, 252):
        assert volatility_cache_client.get(f"/volatility/AAPL/stats?window={window}").status_code == 200
    assert len(cache_redis.entries) == 5
    assert "mdh:volatility:snapshot:AAPL:provider=lseg" in cache_redis.entries


def test_volatility_zero_policy_keeps_closed_history_cache(volatility_cache_client, cache_redis, volatility_env):
    response_cache.policy.values.volatility_seconds = 0
    for suffix in ("", "/history", "/stats"):
        for _ in range(2):
            result = volatility_cache_client.get(f"/volatility/AAPL{suffix}")
            assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    assert not cache_redis.entries
    url = "/volatility/AAPL/history?end=2025-12-31"
    assert volatility_cache_client.get(url).headers["x-fastapi-cache"] == "MISS"
    assert volatility_cache_client.get(url).headers["x-fastapi-cache"] == "HIT"
    assert set(cache_redis.ttls.values()) == {604800}


def test_volatility_capability_errors_not_cached(volatility_cache_client, cache_redis, volatility_env):
    for _ in range(2):
        assert volatility_cache_client.get("/volatility/ES/history?provider=ibkr&sec_type=future").status_code == 501
        assert volatility_cache_client.get("/volatility/AAPL/stats?provider=ibkr&tenor_days=60").status_code == 501
    volatility_env.ibkr.get_implied_volatility_history.assert_not_awaited()
    assert not cache_redis.entries


@pytest.mark.parametrize("name,method,route", [
    ("get_implied_volatility", "get_implied_volatility", "volatility:snapshot"),
    ("get_implied_volatility_history", "get_implied_volatility_history", "volatility:history"),
    ("get_implied_volatility_stats", "get_implied_volatility_history", "volatility:stats"),
])
async def test_volatility_mcp_cache_refresh(volatility_cache_client, cache_redis, volatility_env, name, method, route):
    args = {"symbol": "aapl"}
    handler = mcp.TOOL_HANDLERS[name]
    first = await handler(args)
    assert await handler(args) == first
    assert getattr(volatility_env.lseg, method).await_count == 1
    assert f"mdh:{route}:AAPL:channel=mcp&provider=lseg" in cache_redis.entries
    await handler({**args, "refresh": True})
    assert getattr(volatility_env.lseg, method).await_count == 2
    schema = next(tool for tool in mcp.TOOL_REGISTRY if tool["name"] == name)
    assert schema["inputSchema"]["properties"]["refresh"]["type"] == "boolean"


def test_volatility_http_bypass(volatility_cache_client, volatility_env):
    volatility_cache_client.get("/volatility/AAPL")
    response = volatility_cache_client.get("/volatility/AAPL", headers={"Cache-Control": "no-cache"})
    assert response.headers["x-fastapi-cache"] == "MISS"
    assert volatility_env.lseg.get_implied_volatility.await_count == 2
