import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from financialdatasets_contract import validate_request

from app.providers import request_budget
from app.providers.alphavantage import AlphaVantageProvider, calendar_horizon
from app.providers.financialdatasets import FinancialDatasetsProvider, _price_day
from app.utils.errors import AppError, DataValidationError

FIXTURES = Path(__file__).parent / "fixtures"
START = datetime(2025, 1, 1, tzinfo=UTC)
END = datetime(2027, 1, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    request_budget._local.clear()
    monkeypatch.setattr(request_budget, "budget_redis", lambda: None)
    monkeypatch.setattr("app.models.earnings.earnings_today", lambda: date(2026, 11, 17))
    monkeypatch.setattr("app.providers.alphavantage.earnings_today", lambda: date(2026, 11, 17))
    monkeypatch.setattr("app.providers.metered.get_provider_credential_sync", lambda *args: "fixture-key")
    monkeypatch.setattr("app.providers.alphavantage.get_provider_credential_sync", lambda *args: "fixture-key")


def provider_with_transport(cls, handler):
    provider = cls()
    provider.minimum_spacing = provider.rate_limit_per_sec = 0
    provider.retry_count = 0
    provider._client = httpx.AsyncClient(base_url=provider.base_url, transport=httpx.MockTransport(handler))
    return provider


def fixture_response(directory, name, status=200):
    return httpx.Response(status, content=(FIXTURES / directory / name).read_bytes())


async def test_calendar_one_request_and_share_classes():
    requests = []

    def handler(request):
        requests.append(request)
        return fixture_response("alphavantage", "cal_12m.csv")

    provider = provider_with_transport(AlphaVantageProvider, handler)
    events = await provider.get_upcoming_earnings(date(2026, 11, 17), date(2027, 6, 1), None)
    assert len(requests) == 1
    assert "symbol" not in requests[0].url.params
    assert requests[0].url.params["horizon"] == "12month"
    assert "BF.B" in {event.symbol for event in events}
    assert not any("-P" in event.symbol for event in events)
    assert {event.report_time for event in events} == {"unknown", "bmo", "amc"}
    assert any(event.eps_estimate is None for event in events)
    assert all(event.date_status == "unknown" for event in events)
    await provider.close()


@pytest.mark.parametrize("end,horizon", [(date(2027, 2, 17), "3month"), (date(2027, 5, 17), "6month"), (date(2027, 6, 5), "12month")])
def test_horizon_calendar_month_boundaries(end, horizon):
    assert calendar_horizon(end, date(2026, 11, 17)) == horizon


async def test_calendar_local_root_and_range_filter():
    provider = provider_with_transport(AlphaVantageProvider, lambda _: fixture_response("alphavantage", "cal_12m.csv"))
    events = await provider.get_upcoming_earnings(date(2026, 12, 1), date(2026, 12, 10), ["BF.B"])
    assert [event.symbol for event in events] == ["BF.B"]
    await provider.close()


@pytest.mark.parametrize("root,name", [("AAPL", "earn_AAPL.json"), ("BRK.B", "earn_BRK-B.json")])
async def test_alpha_history_mapping(root, name):
    def handler(request):
        assert request.url.params["symbol"] == root.replace(".", "-")
        return fixture_response("alphavantage", name)

    provider = provider_with_transport(AlphaVantageProvider, handler)
    events = await provider.get_earnings_history(root)
    assert len(events) > 100 and all(event.symbol == root and event.reported for event in events)
    assert all(event.date_status == "confirmed" for event in events)
    assert any(event.eps_estimate is None for event in events)
    assert isinstance(events[0].eps_actual, Decimal)
    await provider.close()


async def test_alpha_unknown_symbol():
    provider = provider_with_transport(AlphaVantageProvider, lambda _: httpx.Response(200, json={}))
    with pytest.raises(AppError) as error:
        await provider.get_earnings_history("ZZZZ")
    assert error.value.code == "DATA_NOT_FOUND"
    await provider.close()


async def test_alpha_compact_window_week_bucket_and_quote_time():
    def handler(request):
        names = {"TIME_SERIES_DAILY": "daily_compact_AAPL.json", "TIME_SERIES_WEEKLY": "weekly_AAPL.json", "GLOBAL_QUOTE": "quote_AAPL.json"}
        return fixture_response("alphavantage", names[request.url.params["function"]])

    provider = provider_with_transport(AlphaVantageProvider, handler)
    bars = await provider.get_historical_prices("AAPL", "1d", START, END)
    assert len(bars) == 100
    assert bars[0].start.tzinfo is not None
    weekly = await provider.get_historical_prices("AAPL", "1w", datetime(2020, 8, 1, tzinfo=UTC), datetime(2020, 10, 1, tzinfo=UTC))
    assert all(bar.start.weekday() == 0 and bar.start.hour == 0 for bar in weekly)
    assert any(bar.close > 490 for bar in weekly) and any(bar.close < 130 for bar in weekly)
    quote = await provider.get_last_price("AAPL")
    assert quote.timestamp.hour == 16
    assert quote.timestamp.date().isoformat() == json.loads((FIXTURES / "alphavantage/quote_AAPL.json").read_text())["Global Quote"]["07. latest trading day"]
    result = await provider.test_connection()
    assert result["success"]
    await provider.close()


async def test_alpha_intraday_rejected_without_request():
    handler = AsyncMock()
    provider = provider_with_transport(AlphaVantageProvider, handler)
    with pytest.raises(DataValidationError):
        await provider.get_historical_prices("AAPL", "1h", START, END)
    handler.assert_not_called()
    await provider.close()


@pytest.mark.parametrize("payload,code,exhausted", [
    ({"Information": "Our standard API rate limit is 25 requests per day. Please subscribe to our premium plans."}, "PROVIDER_QUOTA_EXHAUSTED", True),
    ({"Note": "Daily request quota exhausted"}, "PROVIDER_QUOTA_EXHAUSTED", True),
    ({"Information": "This is a premium endpoint."}, "PROVIDER_NOT_ENTITLED", False),
    ({"Information": "Your API key is invalid"}, "PROVIDER_NOT_AVAILABLE", False),
    ({"Error Message": "Invalid API call"}, "DATA_NOT_FOUND", False),
])
async def test_alpha_notice_classification(payload, code, exhausted):
    provider = provider_with_transport(AlphaVantageProvider, lambda _: httpx.Response(200, json=payload))
    with pytest.raises(AppError) as error:
        await provider.get_last_price("AAPL")
    assert error.value.code == code
    assert (await provider.budget.usage())["day_exhausted"] is exhausted
    await provider.close()


async def test_burst_notice_does_not_exhaust_day_and_retries(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return fixture_response("alphavantage", "burst_limit.json" if len(requests) == 1 else "quote_AAPL.json")

    provider = provider_with_transport(AlphaVantageProvider, handler)
    provider.retry_count = 1
    provider.retry_backoff_seconds = 0
    await provider.get_last_price("AAPL")
    usage = await provider.budget.usage()
    assert len(requests) == 2 and usage["day"]["used"] == 2
    assert usage["day_exhausted"] is False
    await provider.close()


async def test_budget_shared_and_refusal_has_no_upstream_call():
    requests = []

    def handler(request):
        requests.append(request)
        return fixture_response("alphavantage", "quote_AAPL.json" if len(requests) == 1 else "earn_AAPL.json")

    provider = provider_with_transport(AlphaVantageProvider, handler)
    provider.budget.configure({"request_budget_per_day": 2})
    await provider.get_last_price("AAPL")
    await provider.get_earnings_history("AAPL")
    with pytest.raises(AppError) as error:
        await provider.get_last_price("AAPL")
    assert error.value.code == "PROVIDER_QUOTA_EXHAUSTED"
    assert len(requests) == 2
    await provider.close()


def fd_handler(request):
    validate_request(request)  # every request built by the real provider
    if request.url.path == "/earnings":
        name = "earnings_page_2.json" if "cursor" in request.url.params else "earnings.json"
    elif request.url.path == "/prices":
        name = "prices_page_2.json" if "cursor" in request.url.params else f"prices_{request.url.params['interval']}.json"
    else:
        name = {"/prices/snapshot": "snapshot.json", "/company/facts": "company_facts.json"}[request.url.path]
    return fixture_response("financialdatasets", name)


async def test_financialdatasets_history_filings_windows_pagination():
    provider = provider_with_transport(FinancialDatasetsProvider, fd_handler)
    events = await provider.get_earnings_history("AAPL")
    assert len(events) == 7
    by_period = {event.fiscal_period_end: event for event in events}
    assert by_period[date(2026, 9, 30)].report_date == date(2026, 10, 29)
    assert by_period[date(2026, 9, 30)].eps_actual == Decimal("1.85")
    assert by_period[date(2026, 9, 30)].report_time == "amc"
    assert by_period[date(2026, 6, 30)].report_time == "bmo"
    assert by_period[date(2026, 3, 31)].report_time == "during"
    assert by_period[date(2025, 12, 31)].report_time == "unknown"
    # Prior-year comparatives in later 8-Ks neither move nor create events.
    assert by_period[date(2025, 9, 30)].report_date == date(2025, 10, 30)
    assert date(2024, 9, 30) not in by_period
    assert by_period[date(2026, 3, 31)].eps_actual == Decimal("1.65")
    assert all(event.eps_estimate is None and event.reported for event in events)
    assert (await provider.budget.usage())["month"]["used"] == 2
    await provider.close()


async def test_financialdatasets_prices_profile_snapshot_and_no_search():
    provider = provider_with_transport(FinancialDatasetsProvider, fd_handler)
    daily = await provider.get_historical_prices("AAPL", "1d", START, END)
    assert len(daily) == 2 and daily[1].volume == 0
    assert [bar.start.date() for bar in daily] == [date(2026, 11, 16), date(2026, 11, 17)]
    weekly = await provider.get_historical_prices("AAPL", "1w", START, END)
    # Weeks are labelled by their closing Sunday upstream.
    assert [bar.start.date() for bar in weekly] == [date(2026, 11, 9), date(2026, 11, 16)]
    quote = await provider.get_last_price("AAPL")
    assert quote.price == Decimal("224.4")
    profile = await provider.get_company_profile("AAPL")
    assert profile.name == "Apple Inc." and profile.industry == "Consumer Electronics"
    with pytest.raises(AppError) as error:
        await provider.search_companies("apple")
    assert error.value.code == "CAPABILITY_NOT_SUPPORTED"
    await provider.close()


@pytest.mark.parametrize("raw,day", [
    ("2026-11-02", date(2026, 11, 2)),  # live API: bare trading date
    ("2026-11-02T21:00:00Z", date(2026, 11, 2)),  # documented schema: UTC timestamp
    ("2026-11-03T02:00:00Z", date(2026, 11, 2)),
])
def test_financialdatasets_price_day(raw, day):
    assert _price_day(raw) == day


@pytest.mark.parametrize("status,code", [(401, "PROVIDER_NOT_AVAILABLE"), (402, "PROVIDER_NOT_AVAILABLE"), (404, "DATA_NOT_FOUND")])
async def test_financialdatasets_errors(status, code):
    provider = provider_with_transport(FinancialDatasetsProvider, lambda _: fixture_response("financialdatasets", f"error_{status}.json", status))
    with pytest.raises(AppError) as error:
        await provider.get_earnings_history("AAPL")
    assert error.value.code == code
    await provider.close()


async def test_financialdatasets_does_not_forward_key_to_external_page():
    provider = provider_with_transport(FinancialDatasetsProvider, lambda _: httpx.Response(200, json={"earnings": [], "next_page_url": "https://attacker.test/earnings?cursor=x"}))
    with pytest.raises(AppError, match="Unsafe"):
        await provider.get_earnings_history("AAPL")
    await provider.close()


async def test_persistent_burst_stays_timeout_without_day_exhaustion():
    provider = provider_with_transport(AlphaVantageProvider, lambda _: fixture_response("alphavantage", "burst_limit.json"))
    with pytest.raises(AppError) as error:
        await provider.get_last_price("AAPL")
    assert error.value.code == "PROVIDER_TIMEOUT"
    assert (await provider.budget.usage())["day_exhausted"] is False
    await provider.close()


async def test_runtime_timeout_retry_and_budget_config(tmp_path):
    from app.admin.provider_config_repository import ProviderConfigRepository

    config = await ProviderConfigRepository(str(tmp_path / "config.db")).save("alphavantage", {
        "timeout_seconds": 7.5, "retry_count": 0, "rate_limit_per_sec": 2,
        "connection_config": {"request_budget_per_day": 10},
    })
    captured = []

    def handler(request):
        captured.append(request)
        return fixture_response("alphavantage", "quote_AAPL.json")

    provider = provider_with_transport(AlphaVantageProvider, handler)
    provider.configure(config)
    await provider.get_last_price("AAPL")
    assert captured[0].extensions["timeout"]["read"] == 7.5
    assert (await provider.budget.usage())["day"]["budget"] == 10
    await provider.close()


async def test_missing_key_refuses_before_request(monkeypatch):
    def no_key(*args):
        raise AppError("API key is missing", "PROVIDER_NOT_AVAILABLE")

    handler = AsyncMock()
    monkeypatch.setattr("app.providers.alphavantage.get_provider_credential_sync", no_key)
    provider = provider_with_transport(AlphaVantageProvider, handler)
    with pytest.raises(AppError) as error:
        await provider.get_last_price("AAPL")
    assert error.value.code == "PROVIDER_NOT_AVAILABLE"
    handler.assert_not_called()
    assert (await provider.budget.usage())["day"]["used"] == 0
    await provider.close()
