import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from app import dependencies
from app.admin.provider_config_repository import ProviderConfigRepository
from app.admin.settings_repository import SettingsRepository
from app.api import routes_admin
from app.config import settings
from app.main import app
from app.providers import ibkr_web_contracts
from app.providers import registry as registry_module
from app.providers.ibkr_web import IbkrWebProvider
from app.providers.ibkr_web_config import IbkrWebConnectionConfig
from app.providers.ibkr_web_contracts import IbkrWebContracts
from app.providers.ibkr_web_marketdata import number, quantity
from app.providers.ibkr_web_session import GatewayPacer, IbkrWebSession
from app.providers.registry import ProviderRegistry
from app.services.company_service import CompanyService
from app.services.news_service import NewsService
from app.services.options_service import OptionsService
from app.services.price_service import PriceService
from app.services.volatility_service import VolatilityService
from app.utils.errors import (
    CapabilityNotSupportedError,
    DataNotFoundError,
    DataValidationError,
    ProviderNotEntitledError,
)

DATA = json.loads((Path(__file__).parents[1] / "fixtures/ibkrweb/gateway_responses.json").read_text())
SEARCH = "iserver/secdef/search"
SNAPSHOT = "iserver/marketdata/snapshot"
HISTORY = "iserver/marketdata/history"
OPTION_INFO = "iserver/secdef/info"
SCHEDULE = "contract/trading-schedule"


@pytest.fixture
async def make_provider(monkeypatch):
    providers = []
    monkeypatch.setattr(settings, "IBKRWEB_ALERT_WEBHOOK_URL", "")

    def make(handler, *, redis_backend=lambda: None, max_streams=80):
        calls = []
        clock = 0.0

        async def advance(delay):
            nonlocal clock
            clock += delay

        def handle(request):
            path = request.url.path.removeprefix("/v1/api/")
            params = dict(request.url.params)
            calls.append((path, params))
            if path == "iserver/auth/status":
                return httpx.Response(200, json=DATA["status_ready"])
            if path == "iserver/accounts":
                return httpx.Response(200, json=DATA["accounts"])
            value = handler(path, params)
            return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value)

        gateway = IbkrWebSession(
            IbkrWebConnectionConfig.from_settings({"max_streams": max_streams}),
            timeout=1, transport=httpx.MockTransport(handle),
            pacer=GatewayPacer(6, clock=lambda: clock, sleep=advance),
        )
        provider = IbkrWebProvider(session=gateway)
        provider._contract_resolver = IbkrWebContracts(gateway, redis_backend=redis_backend)
        providers.append(provider)
        return provider, calls

    yield make
    for provider in providers:
        await provider.close()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("C1,300.00", "1300"), ("H 130.88", "130.88"), ("N/A", None), ("NaN", None), ("-0.177", "-0.177")],
)
def test_ibkr_web_numeric_field_formats(raw, expected):
    assert number(raw, last=True) == (Decimal(expected) if expected is not None else None)
    assert quantity(None, fallback="8.24K") == 8240
    assert quantity("39856904", fallback="39.9M") == 39856904


async def test_snapshot_preflight_then_delayed_quote_and_stream_budget(make_provider):
    snapshot_polls = 0

    def handle(path, params):
        nonlocal snapshot_polls
        if path == "trsrv/stocks":
            return DATA["stocks"]
        if path == SCHEDULE:
            return DATA["schedule"]
        if path == "iserver/marketdata/unsubscribeall":
            return {"result": True}
        assert path == SNAPSHOT
        snapshot_polls += 1
        if snapshot_polls == 1:
            return [{"conid": 265598, "conidEx": "265598"}]
        if params["conids"] == "756733":
            return [{"conid": 756733, "31": "710.0", "6509": "D"}]
        assert "7762" in params["fields"]
        return DATA["snapshot"]

    provider, calls = make_provider(handle, max_streams=1)
    result = await provider.get_last_price("AAPL")
    assert result.price == Decimal("348.80") and result.volume == 39856904
    assert result.timestamp.tzinfo is UTC
    with pytest.raises(ProviderNotEntitledError) as err:
        await provider.get_last_price("AAPL", market_data_type=1)
    assert err.value.details["symbol"] == "AAPL"
    assert (await provider.get_last_price("SPY", sec_type="etf")).price == Decimal("710.0")
    paths = [path for path, _ in calls]
    assert paths.count("trsrv/stocks") == 2
    assert paths.count("iserver/marketdata/unsubscribeall") == 1
    assert paths.count(SNAPSHOT) == 4


async def test_index_fallback_uses_same_conid_and_history_factor(make_provider):
    def handle(path, params):
        if path == SEARCH:
            return DATA["search_SPX"]
        if path == SNAPSHOT:
            return [{"conid": 416904, "6509": "N"}]
        if path == SCHEDULE:
            return httpx.Response(404)
        assert path == HISTORY and params["conid"] == "416904"
        return DATA["history_daily"]

    provider, _ = make_provider(handle)
    quote = await provider.get_last_price("SPX", sec_type="index")
    assert (quote.symbol, quote.price, quote.volume, quote.is_market_open) == (
        "I:SPX", Decimal("351.91"), 19666515, None,
    )


async def test_api_acknowledgement_never_falls_back(make_provider):
    def handle(path, params):
        if path == SEARCH:
            assert params["symbol"] == "INDU"
            return DATA["search_INDU"]
        assert path == SNAPSHOT
        return [{"conid": 1935181, "6509": "Ob"}]

    provider, _ = make_provider(handle)
    with pytest.raises(ProviderNotEntitledError) as err:
        await provider.get_last_price("DJI", sec_type="index")
    assert err.value.details["symbol"] == "I:DJI"
    assert "Market Data API Acknowledgement" in err.value.details["hint"]


async def test_front_month_caps_ltd_at_expiry_and_returns_local_symbol(make_provider):
    today = date.today()
    near, far = (int((today + timedelta(days=days)).strftime("%Y%m%d")) for days in (1, 30))

    def handle(path, params):
        if path == "trsrv/futures":
            return {"CL": [
                {"conid": 1, "ltd": far, "expirationDate": near},
                {"conid": 2, "expirationDate": far, "ltd": far},
            ]}
        if path == "iserver/contract/2/info":
            return {"exchange": "NYMEX", "local_symbol": "CLG7", "currency": "USD"}
        if path == SNAPSHOT:
            assert params["conids"] == "2"
            return [{"conid": 2, "6509": "D", "31": "75.50"}]
        assert path == SCHEDULE
        return {"exchange_time_zone": "US/Eastern", "schedules": {}}

    provider, _ = make_provider(handle)
    quote = await provider.get_last_price("CL", sec_type="future")
    assert (quote.symbol, quote.source_instrument, quote.is_market_open) == ("F:CL", "CLG7", False)


async def test_intraday_pages_walk_back_dedupe_and_clip(make_provider):
    end = datetime(2026, 11, 18, 17, tzinfo=UTC)
    start = end - timedelta(minutes=1500)
    page_count = 0

    def row(stamp):
        return {"t": int(stamp.timestamp() * 1000), "o": 10, "h": 11, "l": 9, "c": "10.5", "v": "7.5"}

    def handle(path, params):
        nonlocal page_count
        if path == "trsrv/stocks":
            return DATA["stocks"]
        assert path == HISTORY
        assert params["bar"] == "1min" and params["period"] == "12h"
        assert params["outsideRth"] == "true" and params["direction"] == "-1"
        page_count += 1
        bounds = {1: (-1, 718), 2: (716, 1435), 3: (1433, 2152)}
        lower, upper = bounds[page_count]
        return {"mdAvailability": "S", "volumeFactor": 40,
                "data": [row(end - timedelta(minutes=i)) for i in range(upper, lower - 1, -1)]}

    provider, calls = make_provider(handle)
    bars = await provider.get_historical_prices("AAPL", "1m", start, end, extended_hours=True)
    assert page_count == 3 and len(bars) == 1501
    assert (bars[0].start, bars[-1].start, bars[0].volume) == (start, end, 300)
    assert len({bar.start for bar in bars}) == len(bars)
    cursors = [params["startTime"] for path, params in calls if path == HISTORY]
    assert cursors == sorted(cursors, reverse=True)


async def test_daily_bars_use_exchange_dates(make_provider):
    def handle(path, _params):
        if path == "trsrv/stocks":
            return DATA["stocks"]
        assert path == HISTORY
        return DATA["history_daily"]

    provider, _ = make_provider(handle)
    bars = await provider.get_historical_prices("AAPL", "1d", datetime(2026, 11, 16), datetime(2026, 11, 17))
    assert [bar.start for bar in bars] == [datetime(2026, 11, 16), datetime(2026, 11, 17)]


async def test_options_expiry_filter_warm_cache_and_name_search_invalidation(make_provider, monkeypatch):
    monkeypatch.setattr(ibkr_web_contracts, "_ttl", lambda _day: 3600)
    expiry = date(2026, 12, 18)

    def handle(path, params):
        if path == SEARCH:
            return DATA["search_apple_name"] if params.get("name") else DATA["search_AAPL"]
        if path == "iserver/secdef/strikes":
            return DATA["strikes"]
        if path == OPTION_INFO:
            assert params.get("right") is None and params["strike"] == "350.0"
            return DATA["option_info"]
        assert path == SNAPSHOT
        assert "939828681" not in params["conids"]
        return DATA["snapshot"]

    provider, calls = make_provider(handle)
    for _ in range(2):
        chain = await provider.get_option_chain("AAPL", expiry, Decimal(350), Decimal(350))
        assert [option.symbol for option in chain.options] == ["AAPL  261218C00350000", "AAPL  261218P00350000"]
        assert chain.options[0].open_interest == 27600 and chain.options[0].implied_volatility == 0.248
    assert [path for path, _ in calls].count(OPTION_INFO) == 1
    assert [path for path, _ in calls].count("iserver/secdef/strikes") == 1
    quote = await provider.get_option_quote("AAPL", chain.options[0].symbol)
    assert quote.price == Decimal("10.15")
    company = (await provider.search_companies("apple"))[0]
    assert (company.symbol, company.name, company.exchange) == ("AAPL", "APPLE INC", "NASDAQ")
    await provider.get_option_chain("AAPL", expiry, Decimal(350), Decimal(350))
    assert [params.get("name") for path, params in calls if path == SEARCH] == [None, "true", None]


async def test_iv_profile_and_unsupported_operations(make_provider):
    def handle(path, params):
        if path == "trsrv/stocks":
            return DATA["stocks"]
        if path == SNAPSHOT:
            assert params["fields"] == "7283,6509"
            return DATA["snapshot"]
        assert path == "iserver/contract/265598/info"
        return DATA["contract_info"]

    provider, calls = make_provider(handle)
    with pytest.raises(DataNotFoundError):
        await provider.get_option_quote("AAPL", "AAPL-200C")
    with pytest.raises(CapabilityNotSupportedError):
        await provider.get_implied_volatility_history("AAPL", date(2026, 10, 1), date(2026, 11, 1))
    assert not calls
    iv = await provider.get_implied_volatility("AAPL")
    assert [tenor.iv for tenor in iv.implied] == [Decimal("0.2360"), None, None]
    profile = await provider.get_company_profile("AAPL")
    assert (profile.name, profile.industry, profile.exchange) == ("APPLE INC", "Computers", "NASDAQ")
    assert [path for path, _ in calls].count("iserver/contract/265598/info") == 1


async def test_contract_caches_use_redis_namespace_and_fall_back_locally(make_provider):
    class Backend:
        retry_at = 0

        def __init__(self):
            self.redis = self
            self.records = {}

        async def get_with_ttl(self, key):
            raw, ttl = self.records.get(key, (None, 0))
            return ttl, raw

        async def set(self, key, raw, *, ex):
            self.records[key] = raw, ex

    def handle(path, params):
        assert (path, params["symbols"]) == ("trsrv/stocks", "BRK B")
        return DATA["stocks"]

    backend = Backend()
    first, calls = make_provider(handle, redis_backend=lambda: backend)
    assert (await first.contracts.resolve("BRK.B", "stock")).conid == 72063691
    assert backend.records["mdh:ibkrweb:conid:stock:BRK.B"][1] == 30 * 86400
    second, next_calls = make_provider(handle, redis_backend=lambda: backend)
    assert (await second.contracts.resolve("BRK.B", "stock")).conid == 72063691
    backend.records.clear()
    assert (await second.contracts.resolve("BRK.B", "stock")).conid == 72063691
    assert next_calls == [] and [path for path, _ in calls].count("trsrv/stocks") == 1


async def test_registry_load_close_and_reset_on_gateway_config_change(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ENABLED_PROVIDERS", "none")
    repo = ProviderConfigRepository(str(tmp_path / "keys.db"))
    defaults = SettingsRepository(str(tmp_path / "keys.db"))
    reg = ProviderRegistry()
    config = await repo.get("ibkrweb")
    assert config.enabled is False
    assert config.rate_limit_per_sec == 6
    assert config.connection_config["base_url"] == settings.IBKRWEB_BASE_URL
    try:
        await repo.save("ibkrweb", {"enabled": True})
        await reg.reload_from_config(repo, defaults)
        first = reg.get_provider_instance("ibkrweb")
        assert isinstance(first, IbkrWebProvider) and first.session._keep_alive is not None
        await reg.reload_from_config(repo, defaults)
        assert reg.get_provider_instance("ibkrweb") is first
        await repo.save("ibkrweb", {"connection_config": {"base_url": "https://localhost:5001"}})
        await reg.reload_from_config(repo, defaults)
        second = reg.get_provider_instance("ibkrweb")
        assert isinstance(second, IbkrWebProvider) and second is not first
        assert first.session._client.is_closed and first.session._keep_alive.cancelled()
        assert second.session.config.origin == "https://localhost:5001"
        assert second.session.state == "unknown"
        await repo.save("ibkrweb", {"enabled": False})
        await reg.reload_from_config(repo, defaults)
        assert reg.get_provider_instance("ibkrweb") is None
        assert second.session._client.is_closed
    finally:
        await reg.shutdown()


@pytest.fixture
def api_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_AUTH_ENABLED", False)
    monkeypatch.setattr(settings, "ENABLED_PROVIDERS", "none")
    repo = ProviderConfigRepository(str(tmp_path / "keys.db"))
    defaults = SettingsRepository(str(tmp_path / "keys.db"))
    reg = ProviderRegistry()
    monkeypatch.setattr(registry_module, "registry", reg)
    monkeypatch.setattr(routes_admin, "registry", reg)
    monkeypatch.setattr(routes_admin, "get_provider_config_repository", lambda: repo)
    monkeypatch.setitem(app.dependency_overrides, dependencies.get_price_service, lambda: PriceService(reg))
    monkeypatch.setitem(app.dependency_overrides, dependencies.get_company_service, lambda: CompanyService(reg))
    monkeypatch.setitem(app.dependency_overrides, dependencies.get_options_service, lambda: OptionsService(reg))
    monkeypatch.setitem(app.dependency_overrides, dependencies.get_news_service, lambda: NewsService(reg))
    monkeypatch.setitem(app.dependency_overrides, dependencies.get_volatility_service, lambda: VolatilityService(reg))
    return reg, repo, defaults


async def test_data_routes_and_support_gaps_without_upstream(api_registry, make_provider):
    reg, _, _ = api_registry

    def handle(path, params):
        if path == "trsrv/stocks":
            return DATA["stocks"]
        if path == SEARCH:
            return DATA["search_apple_name"] if params.get("name") else DATA["search_AAPL"]
        if path == "iserver/secdef/strikes":
            return DATA["strikes"]
        if path == OPTION_INFO:
            return DATA["option_info"]
        if path == SNAPSHOT:
            return DATA["snapshot"]
        if path == SCHEDULE:
            return DATA["schedule"]
        if path == "iserver/contract/265598/info":
            return DATA["contract_info"]
        assert path == HISTORY
        return DATA["history_daily"]

    provider, calls = make_provider(handle)
    reg._providers["ibkrweb"] = provider
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        catalog = (await http.get("/providers")).json()["data"]["available"]
        assert all("ibkrweb" in catalog[key] for key in ("price", "options", "company", "volatility"))
        assert "ibkrweb" not in catalog["news"]
        history = await http.get("/volatility/AAPL/history?provider=ibkrweb")
        assert history.status_code == 501 and history.json()["error"]["code"] == "CAPABILITY_NOT_SUPPORTED"
        news = await http.get("/companies/AAPL/news?provider=ibkrweb")
        assert news.status_code == 400 and news.json()["error"]["code"] == "INVALID_PROVIDER"
        assert not calls
        for path, params in (
            ("/prices/AAPL/last", {}),
            ("/prices/AAPL/history", {"interval": "1d", "start": "2026-11-16", "end": "2026-11-17"}),
            ("/options/AAPL/chain", {"expiry": "2026-12-18", "min_strike": 350, "max_strike": 350}),
            ("/options/AAPL/quote/AAPL%20%20261218C00350000", {}),
            ("/companies/AAPL", {}),
            ("/companies/search", {"q": "apple"}),
            ("/volatility/AAPL", {}),
        ):
            response = await http.get(path, params={"provider": "ibkrweb", **params})
            assert response.status_code == 200, (path, response.text)
            data = response.json()["data"]
            assert (data[0] if isinstance(data, list) else data)["provider"] == "ibkrweb"


async def test_admin_gateway_tls_merge_session_status_and_logout(api_registry, make_provider, monkeypatch):
    reg, repo, _ = api_registry

    def handle(path, _params):
        if path == "sso/validate":
            return {"LOGIN_TYPE": 2, "USER_NAME": "TESTUSER", "TOKEN": "MUST_NOT_LEAK"}
        assert path == "logout"
        return {"status": True}

    async def noop_reload(*_args):
        pass

    monkeypatch.setattr(reg, "reload_from_config", noop_reload)
    gateway_path = "/api/admin/providers/ibkrweb/gateway"
    session_path = "/api/admin/providers/ibkrweb/session"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        assert (await http.get(session_path)).json() == {"state": "disabled"}
        denied = await http.put(gateway_path, json={"base_url": "https://10.0.0.5:5000", "verify_tls": False})
        assert denied.status_code == 422 and denied.json()["detail"] == (
            "verify_tls must be true or ca_bundle set for a non-local gateway"
        )  # readable text, not a raw pydantic dump
        response = await http.put(gateway_path, json={"base_url": "https://localhost:5001", "max_streams": 50})
        assert response.status_code == 200
        response = await http.put(gateway_path, json={"market_data_type": 4})
        connection = response.json()["connection_config"]
        assert (connection["base_url"], connection["max_streams"], connection["market_data_type"], connection["compete"]) == (
            "https://localhost:5001", 50, 4, False,
        )
        await repo.save("ibkrweb", {"enabled": True})
        await repo.save("ibkr", {"enabled": True})
        provider, calls = make_provider(handle)
        reg._providers["ibkrweb"] = provider
        overview = (await http.get("/api/admin/providers")).json()
        both = {row["name"]: row for row in overview if row["name"] in {"ibkr", "ibkrweb"}}
        assert len(both) == 2 and all(row["warnings"] == ["ibkr_single_session"] for row in both.values())
        assert both["ibkrweb"]["capabilities"] == ["prices", "options", "companies", "volatility"]
        assert (await http.post(f"{session_path}/init")).json()["state"] == "ready"
        for _ in range(2):
            response = await http.get(session_path)
            assert response.json()["account_mode"] == "paper"
            assert response.json()["username"] == "TESTUSER"
            assert "MUST_NOT_LEAK" not in response.text
        assert [path for path, _ in calls].count("sso/validate") == 1
        assert (await http.post(f"{session_path}/logout")).json()["state"] == "login_required"
        assert (await http.get(session_path)).json()["username"] is None


async def test_slow_snapshot_poll_does_not_block_other_quotes(make_provider, monkeypatch):
    monkeypatch.setattr(settings, "IBKRWEB_IV_TIMEOUT_SECONDS", 1.2)

    def handle(path, params):
        if path == "trsrv/stocks":
            return DATA["stocks"]
        if path == SCHEDULE:
            return httpx.Response(404)
        assert path == SNAPSHOT
        if params["fields"] == "7283,6509":
            return [{"conid": 265598, "6509": "D"}]  # IV never arrives: the poll runs until its timeout
        return DATA["snapshot"]

    provider, _ = make_provider(handle)
    iv = asyncio.create_task(provider.get_implied_volatility("AAPL"))
    await asyncio.sleep(0.1)
    quote = await asyncio.wait_for(provider.get_last_price("AAPL"), timeout=0.5)
    assert quote.price == Decimal("348.80") and not iv.done()
    with pytest.raises(DataNotFoundError):
        await iv


async def test_unsubscribeall_waits_for_active_polls(make_provider, monkeypatch):
    monkeypatch.setattr(settings, "IBKRWEB_IV_TIMEOUT_SECONDS", 0.8)
    events = []

    def handle(path, params):
        if path == "trsrv/stocks":
            return DATA["stocks"]
        if path == SCHEDULE:
            return httpx.Response(404)
        if path == "iserver/marketdata/unsubscribeall":
            events.append("unsubscribeall")
            return {"result": True}
        assert path == SNAPSHOT
        events.append(params["conids"])
        if params["conids"] == "265598":
            return [{"conid": 265598, "6509": "D"}]
        return [{"conid": 756733, "31": "710.0", "6509": "D"}]

    provider, _ = make_provider(handle, max_streams=1)
    iv = asyncio.create_task(provider.get_implied_volatility("AAPL"))
    await asyncio.sleep(0.1)
    assert (await provider.get_last_price("SPY", sec_type="etf")).price == Decimal("710.0")
    with pytest.raises(DataNotFoundError):
        await iv
    first_unsubscribe = events.index("unsubscribeall")
    assert "265598" not in events[first_unsubscribe:] and events[first_unsubscribe + 1] == "756733"


async def test_history_range_beyond_window_budget_is_rejected_without_requests(make_provider):
    provider, calls = make_provider(lambda path, _params: DATA["stocks"] if path == "trsrv/stocks" else pytest.fail(path))
    end = datetime(2026, 11, 18, tzinfo=UTC)
    with pytest.raises(DataValidationError) as error:
        await provider.get_historical_prices("AAPL", "1m", end - timedelta(days=60), end)
    assert error.value.details["interval"] == "1m"
    assert HISTORY not in [path for path, _ in calls]


async def test_failed_fallback_keeps_entitlement_error(make_provider):
    def handle(path, _params):
        if path == SEARCH:
            return DATA["search_SPX"]
        if path == SNAPSHOT:
            return [{"conid": 416904, "6509": "N"}]
        assert path == HISTORY
        return httpx.Response(503, json={"error": "Service unavailable"})

    provider, _ = make_provider(handle)
    with pytest.raises(ProviderNotEntitledError):
        await provider.get_last_price("SPX", sec_type="index")


async def test_option_chain_skips_rejected_strikes_and_caches_misses(make_provider, monkeypatch):
    monkeypatch.setattr(ibkr_web_contracts, "_ttl", lambda _day: 3600)
    expiry = date(2026, 12, 18)

    def handle(path, params):
        if path == SEARCH:
            return DATA["search_AAPL"]
        if path == "iserver/secdef/strikes":
            return DATA["strikes"]
        if path == OPTION_INFO:
            if params["strike"] == "345.0":
                return httpx.Response(400, json={"error": "Invalid strike"})
            if params["strike"] == "347.5":
                return [{**row, "maturityDate": "20261211"} for row in DATA["option_info"]]  # other expiry only
            return DATA["option_info"]
        assert path == SNAPSHOT
        return DATA["snapshot"]

    provider, calls = make_provider(handle)
    for _ in range(2):
        chain = await provider.get_option_chain("AAPL", expiry, Decimal(345), Decimal(350), right="call")
        assert [option.strike for option in chain.options] == [Decimal(350)]
    # The second, warm chain sends no secdef/info at all: hits and misses are both cached.
    assert [path for path, _ in calls].count(OPTION_INFO) == 3


async def test_unknown_expiry_in_listed_month_is_cached(make_provider, monkeypatch):
    monkeypatch.setattr(ibkr_web_contracts, "_ttl", lambda _day: 3600)

    def handle(path, _params):
        if path == SEARCH:
            return DATA["search_AAPL"]
        if path == "iserver/secdef/strikes":
            return DATA["strikes"]
        assert path == OPTION_INFO
        return DATA["option_info"]

    provider, calls = make_provider(handle)
    for _ in range(2):
        chain = await provider.get_option_chain("AAPL", date(2026, 12, 4), Decimal(345), Decimal(350))
        assert (chain.options, chain.provider) == ([], "ibkrweb")
    assert [path for path, _ in calls].count(OPTION_INFO) == 3


@pytest.mark.parametrize(("hours", "expected"), [((-1, 1), True), ((-3, -1), False)])
async def test_market_open_evaluates_todays_trading_schedule(make_provider, hours, expected):
    # Built around "now" so the D9 evaluation runs on every day, not only on the fixture date.
    now = datetime.now(UTC)
    zone = "US/Eastern"
    today = now.astimezone(ZoneInfo(zone)).strftime("%Y%m%d")
    opening, closing = (int((now + timedelta(hours=offset)).timestamp()) for offset in hours)

    def handle(path, _params):
        if path == "trsrv/stocks":
            return DATA["stocks"]
        if path == SCHEDULE:
            return {"exchange_time_zone": zone,
                    "schedules": {today: {"extended_hours": [{"opening": opening, "closing": closing}]}}}
        assert path == SNAPSHOT
        return DATA["snapshot"]

    provider, _ = make_provider(handle)
    assert (await provider.get_last_price("AAPL")).is_market_open is expected


async def test_cold_chain_looks_up_strikes_concurrently(make_provider, monkeypatch):
    monkeypatch.setattr(ibkr_web_contracts, "_ttl", lambda _day: 3600)
    expiry = date(2026, 12, 18)

    def handle(path, params):
        if path == SEARCH:
            return DATA["search_AAPL"]
        if path == "iserver/secdef/strikes":
            return DATA["strikes"]
        if path == OPTION_INFO:
            return [{**row, "strike": float(params["strike"])} for row in DATA["option_info"]]
        assert path == SNAPSHOT
        return []

    provider, _ = make_provider(handle)
    in_flight = peak = 0
    request = provider.session.request

    async def tracking(path, **kwargs):
        nonlocal in_flight, peak
        if path != OPTION_INFO:
            return await request(path, **kwargs)
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        try:
            return await request(path, **kwargs)
        finally:
            in_flight -= 1

    monkeypatch.setattr(provider.session, "request", tracking)
    monkeypatch.setattr(settings, "IBKRWEB_OPTION_SNAPSHOT_TIMEOUT_SECONDS", 0.1)
    chain = await provider.get_option_chain("AAPL", expiry, Decimal(345), Decimal(350))
    assert {option.strike for option in chain.options} == {Decimal(345), Decimal("347.5"), Decimal(350)}
    assert peak == 3


async def test_ibkrweb_admin_routes_require_auth(api_registry, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_AUTH_ENABLED", True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        base = "/api/admin/providers/ibkrweb"
        responses = [
            await http.put(f"{base}/gateway", json={"compete": True}),
            await http.get(f"{base}/session"),
            await http.post(f"{base}/session/init"),
            await http.post(f"{base}/session/logout"),
        ]
    assert [response.status_code for response in responses] == [401] * 4


async def test_registry_reload_survives_failing_reconfigure(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ENABLED_PROVIDERS", "none")
    repo = ProviderConfigRepository(str(tmp_path / "keys.db"))
    defaults = SettingsRepository(str(tmp_path / "keys.db"))
    reg = ProviderRegistry()
    try:
        await repo.save("ibkrweb", {"enabled": True})
        await reg.reload_from_config(repo, defaults)
        provider = reg.get_provider_instance("ibkrweb")

        def broken(_config):
            raise FileNotFoundError("ca bundle removed")

        monkeypatch.setattr(provider, "requires_replacement", broken)
        await repo.save("mock", {"enabled": True})
        await reg.reload_from_config(repo, defaults)  # must not raise
        assert reg.get_provider_instance("ibkrweb") is provider
        assert reg.get_provider_instance("mock") is not None
    finally:
        await reg.shutdown()
