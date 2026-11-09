"""REST routes resolve namespaced symbols centrally and report canonical symbols."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes_companies, routes_options, routes_prices, routes_volatility
from app.dependencies import (
    get_company_service,
    get_news_service,
    get_options_service,
    get_price_service,
    get_volatility_service,
)
from app.main import app_error_handler
from app.models.company import CompanyProfile
from app.models.options import OptionChain, OptionQuote
from app.models.price import PriceBar, PriceQuote
from app.models.volatility import (
    ImpliedVolatilityTenor,
    VolatilityHistory,
    VolatilityPoint,
    VolatilitySnapshot,
)
from app.providers.base import (
    BaseCompanyProvider,
    BaseOptionsProvider,
    BasePriceProvider,
    BaseVolatilityProvider,
)
from app.providers.registry import ProviderRegistry
from app.services.company_service import CompanyService
from app.services.options_service import OptionsService
from app.services.price_service import PriceService
from app.services.volatility_service import VolatilityService
from app.utils.errors import AppError

NOW = datetime(2026, 11, 6, 12, 30)


def _price_provider(name, types):
    provider = Mock(spec=BasePriceProvider)
    provider.name = name
    provider.price_sec_types = frozenset(types)
    provider.price_history_sec_types = frozenset(types)

    async def last(symbol, market_data_type=None, sec_type="stock"):
        return PriceQuote(
            symbol=symbol, price=Decimal(5000), currency="USD",
            timestamp=NOW, provider=name,
        )

    async def history(symbol, *args, **kwargs):
        return [PriceBar(
            symbol=symbol, start=NOW, end=NOW, open=Decimal(1), high=Decimal(1),
            low=Decimal(1), close=Decimal(1), volume=1, provider=name,
        )]

    provider.get_last_price = AsyncMock(side_effect=last)
    provider.get_historical_prices = AsyncMock(side_effect=history)
    return provider


def _volatility_provider():
    provider = Mock(spec=BaseVolatilityProvider)
    provider.name = "lseg"
    provider.volatility_sec_types = frozenset({"stock", "etf", "index", "future"})
    provider.volatility_history_sec_types = provider.volatility_sec_types
    provider.volatility_tenors = frozenset({30, 60, 90})

    async def snapshot(symbol, sec_type="stock", ric=None):
        return VolatilitySnapshot(
            symbol=symbol, sec_type=sec_type, method="provider_atm_index",
            source_instrument=f"{symbol}ATMIV", underlying=symbol,
            underlying_name=symbol, market="OPRA", as_of=date.today(),
            implied=[ImpliedVolatilityTenor(tenor_days=30, iv="0.25")], provider="lseg",
        )

    async def history(symbol, start, end, tenor_days=30, sec_type="stock", ric=None):
        return VolatilityHistory(
            symbol=symbol, sec_type=sec_type, source_instrument=f"{symbol}ATMIV",
            tenor_days=tenor_days, provider="lseg",
            points=[
                VolatilityPoint(date=date.today() - timedelta(days=index), iv="0.2")
                for index in range(25)
            ],
        )

    provider.get_implied_volatility = AsyncMock(side_effect=snapshot)
    provider.get_implied_volatility_history = AsyncMock(side_effect=history)
    return provider


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(ProviderRegistry, "_initialize_providers", lambda self: None)
    registry = ProviderRegistry()
    ibkr = _price_provider("ibkr", {"stock", "etf", "index", "future"})
    polygon = _price_provider("polygon", {"stock", "etf", "index"})
    volatility = _volatility_provider()
    company = Mock(spec=BaseCompanyProvider)
    company.name = "finnhub"
    company.get_company_profile = AsyncMock(return_value=CompanyProfile(
        symbol="AAPL", name="Apple", exchange="NASDAQ", currency="USD", provider="finnhub",
    ))
    options = Mock(spec=BaseOptionsProvider)
    options.name = "schwab"
    options.option_underlying_sec_types = frozenset({"stock", "etf", "index"})
    options.get_option_chain = AsyncMock(return_value=OptionChain(
        underlying_symbol="SPX", expiry=date(2026, 12, 18), options=[], provider="schwab",
    ))
    options.get_option_quote = AsyncMock()
    registry._providers = {
        "ibkr": ibkr, "polygon": polygon, "lseg": volatility,
        "finnhub": company, "schwab": options,
    }
    registry.default_price_provider = "ibkr"
    registry.default_volatility_provider = "lseg"
    registry.default_company_provider = "finnhub"
    registry.default_options_provider = "schwab"

    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)
    for router in (
        routes_prices.router, routes_volatility.router,
        routes_companies.router, routes_options.router,
    ):
        app.include_router(router)
    app.dependency_overrides[get_price_service] = lambda: PriceService(registry)
    app.dependency_overrides[get_volatility_service] = lambda: VolatilityService(registry)
    app.dependency_overrides[get_company_service] = lambda: CompanyService(registry)
    app.dependency_overrides[get_options_service] = lambda: OptionsService(registry)
    app.dependency_overrides[get_news_service] = lambda: SimpleNamespace(
        registry=registry, get_company_news=AsyncMock(return_value=[])
    )
    return SimpleNamespace(
        client=TestClient(app), ibkr=ibkr, polygon=polygon, lseg=volatility,
        company=company, options=options,
    )


def test_colon_symbol_matches_route_and_reaches_provider_as_bare_root(env):
    response = env.client.get("/volatility/F:ES/stats?provider=lseg")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["symbol"] == "F:ES"
    assert env.lseg.get_implied_volatility_history.call_args.args[0] == "ES"
    assert env.lseg.get_implied_volatility_history.call_args.args[4] == "future"


def test_legacy_sec_type_equals_prefix(env):
    legacy = env.client.get("/volatility/ES?sec_type=future").json()["data"]
    prefixed = env.client.get("/volatility/F:ES").json()["data"]
    assert legacy["symbol"] == prefixed["symbol"] == "F:ES"
    assert legacy["sec_type"] == prefixed["sec_type"] == "future"


def test_sec_type_is_case_insensitive(env):
    response = env.client.get("/volatility/SPX?sec_type=INDEX")
    assert response.status_code == 200
    assert response.json()["data"]["symbol"] == "I:SPX"


def test_contradicting_sec_type_is_422(env):
    response = env.client.get("/volatility/F:ES?sec_type=stock")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DATA_VALIDATION_ERROR"
    env.lseg.get_implied_volatility.assert_not_awaited()


def test_invalid_sec_type_is_422(env):
    response = env.client.get("/prices/AAPL/last?sec_type=bond")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DATA_VALIDATION_ERROR"


@pytest.mark.parametrize("path", [".SPX", "%24SPX"])
def test_provider_native_notation_is_422_with_suggestion(env, path):
    response = env.client.get(f"/volatility/{path}")
    assert response.status_code == 422
    assert response.json()["error"]["details"]["suggestion"] == "I:SPX"


def test_company_profile_for_future_is_422_without_provider_call(env):
    response = env.client.get("/companies/F:ES")
    assert response.status_code == 422
    assert response.json()["error"]["details"]["sec_type"] == "future"
    env.company.get_company_profile.assert_not_awaited()


def test_company_profile_passes_bare_root(env):
    assert env.client.get("/companies/aapl").status_code == 200
    env.company.get_company_profile.assert_awaited_once_with("AAPL")


def test_caret_alias_gives_canonical_symbol(env):
    response = env.client.get("/prices/%5ESPX/last?provider=ibkr")
    assert response.status_code == 200
    assert response.json()["data"]["symbol"] == "I:SPX"
    env.ibkr.get_last_price.assert_awaited_once_with("SPX", None, "index")


def test_history_bars_carry_canonical_symbol(env):
    response = env.client.get("/prices/F:ES/history?provider=ibkr")
    assert response.status_code == 200
    assert {bar["symbol"] for bar in response.json()["data"]} == {"F:ES"}
    assert env.ibkr.get_historical_prices.call_args.args[0] == "ES"
    assert env.ibkr.get_historical_prices.call_args.kwargs["sec_type"] == "future"


def test_stock_symbol_unchanged(env):
    response = env.client.get("/prices/aapl/last")
    assert response.json()["data"]["symbol"] == "AAPL"


@pytest.mark.parametrize("operation", ["last", "history"])
def test_future_at_provider_without_mapping_is_501(env, operation):
    response = env.client.get(f"/prices/F:ES/{operation}?provider=polygon")
    assert response.status_code == 501
    error = response.json()["error"]
    assert error["code"] == "CAPABILITY_NOT_SUPPORTED"
    assert error["details"]["supported"] == ["etf", "index", "stock"]
    env.polygon.get_last_price.assert_not_awaited()
    env.polygon.get_historical_prices.assert_not_awaited()


def test_supported_index_is_forwarded(env):
    response = env.client.get("/prices/I:SPX/last?provider=polygon")
    assert response.status_code == 200
    env.polygon.get_last_price.assert_awaited_once_with("SPX", None, "index")


def test_csv_filename_url_encodes_canonical_symbol(env):
    response = env.client.get("/prices/F:ES/history?provider=ibkr&format=csv")
    assert response.status_code == 200
    assert "F%3AES_history_1d.csv" in response.headers["content-disposition"]
    assert "source_instrument" in response.text.splitlines()[0]


def test_option_chain_on_index_passes_root_and_type(env):
    response = env.client.get("/options/I:SPX/chain?expiry=2026-12-18")
    assert response.status_code == 200
    assert response.json()["data"]["underlying_symbol"] == "I:SPX"
    assert env.options.get_option_chain.call_args.args[0] == "SPX"
    assert env.options.get_option_chain.call_args.kwargs["sec_type"] == "index"


def test_option_underlying_rejects_future(env):
    assert env.client.get("/options/F:ES/chain").status_code == 422
    assert env.client.get("/options/O:AAPL250117C00150000/chain").status_code == 422


def test_option_quote_strips_option_prefix(env):
    env.options.get_option_quote.return_value = OptionQuote(
        symbol="AAPL250117C00150000", underlying_symbol="AAPL", strike=Decimal(150),
        expiry=date(2025, 1, 17), type="call", price=Decimal(5), currency="USD",
        provider="schwab",
    )
    response = env.client.get("/options/AAPL/quote/O:aapl250117c00150000")
    assert response.status_code == 200
    assert env.options.get_option_quote.call_args.args[:2] == (
        "AAPL", "AAPL250117C00150000",
    )


@pytest.mark.parametrize("path", ["/prices/X:BTC/last", "/volatility/F:/stats"])
def test_malformed_symbols_are_422(env, path):
    response = env.client.get(path)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DATA_VALIDATION_ERROR"


def test_malformed_symbol_with_cache_is_422_and_not_cached(env, cache_redis):
    response = env.client.get("/volatility/F:ES/stats?sec_type=stock")
    assert response.status_code == 422
    assert cache_redis.entries == {}


def test_namespaced_requests_share_cache_entry(env, cache_redis):
    first = env.client.get("/prices/^SPX/history?provider=ibkr")
    second = env.client.get("/prices/I:SPX/history?provider=ibkr")
    assert first.status_code == second.status_code == 200
    assert second.headers["x-fastapi-cache"] == "HIT"
    assert list(cache_redis.entries) == ["mdh:prices:history:I%3ASPX:provider=ibkr"]
    assert env.ibkr.get_historical_prices.await_count == 1


async def test_rest_and_mcp_share_resolution_and_cache_partition(env, cache_redis, monkeypatch):
    from app.api import mcp

    registry_service = VolatilityService(env.client.app.dependency_overrides[get_volatility_service]().registry)
    monkeypatch.setattr(mcp, "_volatility_service", lambda: registry_service)
    rest = env.client.get("/volatility/I:SPX/stats?provider=lseg")
    assert rest.status_code == 200
    await mcp._dispatch(
        "tools/call",
        {"name": "get_implied_volatility_stats",
         "arguments": {"symbol": "I:SPX", "provider": "lseg"}},
    )
    assert sorted(cache_redis.entries) == [
        "mdh:volatility:stats:I%3ASPX:channel=mcp&provider=lseg",
        "mdh:volatility:stats:I%3ASPX:provider=lseg",
    ]
    calls = env.lseg.get_implied_volatility_history.call_args_list
    assert calls[0].args[0] == calls[1].args[0] == "SPX"
    assert calls[0].args[4] == calls[1].args[4] == "index"
