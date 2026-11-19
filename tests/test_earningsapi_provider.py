from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.providers import request_budget
from app.providers.base import BaseEarningsHistoryProvider, BaseEarningsUpcomingProvider
from app.providers.earningsapi import EarningsApiProvider
from app.utils.errors import (
    AppError,
    CapabilityNotSupportedError,
    DataNotFoundError,
    ProviderError,
    ProviderQuotaExhaustedError,
)

FIXTURES = Path(__file__).parent / "fixtures" / "earningsapi"


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    request_budget._local.clear()
    monkeypatch.setattr(request_budget, "budget_redis", lambda: None)
    monkeypatch.setattr("app.models.earnings.earnings_today", lambda: date(2026, 11, 19))
    monkeypatch.setattr("app.providers.earningsapi.get_provider_credential_sync", lambda *args: "fixture-key")


def make(handler, retries=0):
    provider = EarningsApiProvider()
    provider.minimum_spacing = provider.rate_limit_per_sec = 0
    provider.retry_count = retries
    provider.retry_backoff_seconds = 0
    provider._client = httpx.AsyncClient(base_url=provider.base_url, transport=httpx.MockTransport(handler))
    return provider


def fixture(name, status=200, headers=None):
    return httpx.Response(status, content=(FIXTURES / name).read_bytes(), headers=headers)


def test_interfaces_and_mode():
    provider = EarningsApiProvider()
    assert isinstance(provider, BaseEarningsUpcomingProvider) and isinstance(provider, BaseEarningsHistoryProvider)
    assert provider.upcoming_mode == "symbol" and provider.earnings_day_calendar


async def test_symbol_mapping_adi():
    seen = []

    def handler(request):
        seen.append(request.url)
        return fixture("earnings_ADI.json")

    provider = make(handler)
    events = await provider.get_symbol_earnings("adi")
    assert seen[0].params["symbol"] == "ADI" and seen[0].params["apikey"] == "fixture-key"
    upcoming = events[0]
    assert upcoming.report_date == date(2026, 11, 24) and not upcoming.reported
    assert upcoming.report_time == "bmo" and upcoming.date_status == "unknown"
    assert upcoming.eps_actual is None and upcoming.revenue_estimate == Decimal(4319898951)
    reported = next(e for e in events if e.report_date == date(2026, 8, 19))
    assert reported.reported and reported.date_status == "confirmed"
    assert reported.eps_surprise == Decimal("0.112549")
    assert reported.eps_surprise_pct.quantize(Decimal("0.01")) == Decimal("3.37")
    assert reported.revenue_actual == Decimal(4021899000) and reported.currency == "USD"
    assert {e.symbol for e in events} == {"ADI"}
    await provider.close()


async def test_null_time_and_after_hours():
    rows = [
        {"date": "2026-11-02", "symbol": "X", "time": "time-after-hours", "epsEstimate": 1, "eps": 2, "revenue": None, "revenueEstimate": None},
        {"date": "2026-08-01", "symbol": "X", "time": None, "epsEstimate": 0, "eps": 1, "revenue": None, "revenueEstimate": None},
    ]
    provider = make(lambda _: httpx.Response(200, json=rows))
    events = await provider.get_symbol_earnings("X")
    assert [e.report_time for e in events] == ["amc", "unknown"]
    assert events[1].eps_surprise == Decimal(1) and events[1].eps_surprise_pct is None  # estimate 0
    await provider.close()


async def test_history_returns_reported_only():
    provider = make(lambda _: fixture("earnings_ADI.json"))
    events = await provider.get_earnings_history("ADI")
    assert events and all(e.reported for e in events)
    await provider.close()


async def test_unknown_symbol_is_not_found():
    provider = make(lambda _: fixture("error_symbol_not_found.json", 404))
    with pytest.raises(DataNotFoundError):
        await provider.get_symbol_earnings("ZZZZQX")
    provider = make(lambda _: httpx.Response(200, json=[]))
    with pytest.raises(DataNotFoundError):
        await provider.get_symbol_earnings("ZZZZQX")


async def test_invalid_key():
    provider = make(lambda _: fixture("error_invalid_key.txt", 403))
    with pytest.raises(ProviderError) as info:
        await provider.get_symbol_earnings("ADI")
    assert info.value.code == "PROVIDER_NOT_AVAILABLE"
    result = await provider.test_connection()
    assert result["success"] is False


async def test_unexpected_shape_is_provider_error():
    provider = make(lambda _: httpx.Response(200, json={"oops": 1}))
    with pytest.raises(ProviderError) as info:
        await provider.get_symbol_earnings("ADI")
    assert info.value.code == "PROVIDER_ERROR"
    provider = make(lambda _: httpx.Response(200, json={"date": "2026-11-24"}))
    with pytest.raises(ProviderError):
        await provider.get_earnings_for_date(date(2026, 11, 24))


async def test_day_calendar_groups_and_duplicates():
    seen = []

    def handler(request):
        seen.append(request.url)
        return fixture("calendar_2026-11-24.json")

    provider = make(handler)
    events = await provider.get_earnings_for_date(date(2026, 11, 24))
    assert seen[0].params["date"] == "2026-11-24"
    by_symbol = {e.symbol: e for e in events}
    assert by_symbol["ADI"].report_time == "bmo" and by_symbol["ADI"].report_date == date(2026, 11, 24)
    assert len(by_symbol) == len(events)
    assert {e.report_time for e in events} <= {"bmo", "amc", "unknown"}
    assert all(not e.reported for e in events if e.eps_actual is None)
    await provider.close()


async def test_day_calendar_duplicate_prefers_known_time():
    payload = {
        "date": "2026-11-24",
        "pre": [],
        "after": [{"symbol": "DLTR", "epsEstimate": 1}],
        "notSupplied": [{"symbol": "DLTR"}, {"symbol": "bad symbol!"}, {"name": "no symbol"}],
    }
    provider = make(lambda _: httpx.Response(200, json=payload))
    events = await provider.get_earnings_for_date(date(2026, 11, 24))
    assert [(e.symbol, e.report_time) for e in events] == [("DLTR", "amc")]


async def test_day_calendar_actuals_and_empty_day():
    provider = make(lambda _: fixture("calendar_2026-11-18_actuals.json"))
    events = await provider.get_earnings_for_date(date(2026, 11, 18))
    assert any(e.reported and e.eps_actual is not None for e in events)
    provider = make(lambda _: fixture("calendar_empty_day.json"))
    assert await provider.get_earnings_for_date(date(2026, 11, 21)) == []


async def test_upcoming_calendar_mode_not_supported_without_request():
    def handler(request):
        raise AssertionError("no request expected")

    provider = make(handler)
    with pytest.raises(CapabilityNotSupportedError):
        await provider.get_upcoming_earnings(date(2026, 11, 19), date(2026, 12, 19), None)


async def test_per_minute_429_is_retried_with_retry_after():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, text="slow down", headers={"Retry-After": "0"})
        return fixture("earnings_ADI.json")

    provider = make(handler, retries=1)
    assert await provider.get_symbol_earnings("ADI")
    assert len(calls) == 2


async def test_daily_quota_exhausts_budget_without_retry():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, text="quota", headers={"X-Daily-Remaining": "0"})

    provider = make(handler, retries=2)
    with pytest.raises(ProviderQuotaExhaustedError) as info:
        await provider.get_symbol_earnings("ADI")
    assert info.value.details["period"] == "day" and len(calls) == 1
    with pytest.raises(ProviderQuotaExhaustedError):
        await provider.get_symbol_earnings("ADI")
    assert len(calls) == 1  # budget refuses without a request


async def test_monthly_quota_header():
    provider = make(lambda _: httpx.Response(429, headers={"X-Quota-Remaining": "0"}))
    with pytest.raises(ProviderQuotaExhaustedError) as info:
        await provider.get_symbol_earnings("ADI")
    assert info.value.details["period"] == "month"


async def test_budget_refusal_and_metric(monkeypatch):
    provider = make(lambda _: fixture("earnings_ADI.json"))
    provider.budget.day_budget = 1
    await provider.get_symbol_earnings("ADI")
    calls = []
    provider._client = httpx.AsyncClient(
        base_url=provider.base_url, transport=httpx.MockTransport(lambda r: calls.append(r) or fixture("earnings_ADI.json"))
    )
    with pytest.raises(AppError) as info:
        await provider.get_symbol_earnings("ADI")
    assert info.value.code == "PROVIDER_QUOTA_EXHAUSTED" and calls == []


async def test_connection_success():
    seen = []
    provider = make(lambda r: seen.append(r) or fixture("earnings_ADI.json"))
    result = await provider.test_connection()
    assert result["success"] and seen[0].url.params["symbol"] == "AAPL" and len(seen) == 1


def test_fixtures_hold_no_key():
    for path in FIXTURES.iterdir():
        assert "apikey" not in path.read_text().lower()
