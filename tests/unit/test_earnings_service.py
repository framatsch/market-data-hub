"""Earnings service without the store: fake provider recording every call."""

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app import response_meta
from app.models.earnings import EarningsEvent
from app.providers.base import BaseEarningsHistoryProvider, BaseEarningsUpcomingProvider
from app.providers.registry import ProviderRegistry
from app.services import earnings_service as module
from app.services.earnings_service import (
    EarningsService,
    parse_symbol_list,
    reconcile_events,
)
from app.utils.errors import (
    AppError,
    CapabilityNotSupportedError,
    DataNotFoundError,
    DataValidationError,
    ProviderConnectionError,
    ProviderQuotaExhaustedError,
)

TODAY = date(2026, 11, 17)


class FakeRedis:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex=None):
        self.values[key] = value


class FakeBudget:
    def __init__(self, remaining):
        self._remaining = remaining

    async def remaining(self):
        return self._remaining

    async def usage(self):
        return {"day": {"budget": 25, "used": 25}, "month": {"budget": 0, "used": 90}, "day_exhausted": False}


class FakeProvider(BaseEarningsUpcomingProvider, BaseEarningsHistoryProvider):
    name = "fake"

    def __init__(self, calendar=(), history=None, upcoming=True, budget=None):
        self.calendar = list(calendar)
        self.history = history or {}
        self.budget = budget
        self.calendar_calls = []
        self.history_calls = []
        self.calendar_error = None

    async def get_upcoming_earnings(self, start, end, roots):
        self.calendar_calls.append((start, end, roots))
        if self.calendar_error:
            raise self.calendar_error
        return list(self.calendar)

    async def get_earnings_history(self, root):
        self.history_calls.append(root)
        result = self.history.get(root, DataNotFoundError("Earnings", root))
        if isinstance(result, Exception):
            raise result
        return list(result)

    async def test_connection(self):
        return {"success": True}


class HistoryOnlyProvider(BaseEarningsHistoryProvider):
    name = FakeProvider.name
    __init__ = FakeProvider.__init__
    get_earnings_history = FakeProvider.get_earnings_history
    test_connection = FakeProvider.test_connection


def event(symbol, day, **kwargs):
    return EarningsEvent(symbol=symbol, report_date=day, provider="fake", **kwargs)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr("app.models.earnings.earnings_today", lambda: TODAY)
    monkeypatch.setattr(module, "earnings_today", lambda: TODAY)
    monkeypatch.setattr(module, "budget_redis", lambda: None)


def service(provider):
    monkey = ProviderRegistry.__new__(ProviderRegistry)
    monkey._providers = {"fake": provider}
    monkey.default_earnings_history_provider = "fake"
    monkey.default_earnings_upcoming_provider = (
        "fake" if isinstance(provider, BaseEarningsUpcomingProvider) else None
    )
    monkey._provider_locks = {}
    monkey._provider_inflight = {}
    monkey._provider_drained = {}
    return EarningsService(monkey)


def symbols(text):
    return parse_symbol_list(text)


def test_symbol_parsing_order_dedup_and_limits():
    assert [s.canonical for s in symbols("msft, AAPL,,MSFT ,brk.b")] == ["MSFT", "AAPL", "BRK.B"]
    with pytest.raises(DataValidationError) as error:
        symbols("I:SPX,AAPL")
    assert "I:SPX" in error.value.message
    for bad in ("F:ES", "O:AAPL261218C00200000", ""):
        with pytest.raises(DataValidationError):
            symbols(bad)
    assert len(symbols(",".join(f"S{i}" for i in range(50)))) == 50
    with pytest.raises(DataValidationError):
        symbols(",".join(f"S{i}" for i in range(51)))
    assert len(symbols(",".join(["AAPL"] * 80))) == 1


async def test_next_uses_one_calendar_request_and_no_history():
    provider = FakeProvider([event("AAPL", date(2027, 1, 28), report_time="amc")])
    with_meta = response_meta.begin()
    try:
        result = await service(provider).next(symbols("MSFT,SPY,AAPL"))
        meta = response_meta.current()
    finally:
        response_meta.end(with_meta)
    assert [row.symbol for row in result.rows] == ["MSFT", "SPY", "AAPL"]
    assert [row.status for row in result.rows] == ["none_scheduled", "not_applicable", "ok"]
    assert result.rows[2].days_until == 72 and result.rows[2].event.report_time == "amc"
    assert result.rows[0].event is None and result.rows[0].last_reported is None
    assert provider.history_calls == []
    assert provider.calendar_calls == [(TODAY, TODAY + timedelta(days=365), None)]
    assert meta.data_as_of is not None and not meta.stale


async def test_report_today_has_zero_days_until():
    provider = FakeProvider([event("AAPL", TODAY, report_time="amc")])
    row = (await service(provider).next(symbols("AAPL"))).rows[0]
    assert row.days_until == 0 and row.event.report_time == "amc"


async def test_etf_only_request_makes_no_provider_call():
    provider = FakeProvider()
    result = await service(provider).next(symbols("SPY,QQQ"))
    assert {row.status for row in result.rows} == {"not_applicable"}
    assert provider.calendar_calls == [] and provider.history_calls == []
    explicit = await service(provider).calendar(symbols("SPY"), TODAY, TODAY + timedelta(days=30))
    assert explicit.symbols[0].status == "not_applicable" and explicit.events == []


async def test_redis_calendar_serves_two_different_watchlists(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(module, "budget_redis", lambda: redis)
    provider = FakeProvider([event("AAPL", date(2027, 1, 28)), event("NVDA", date(2027, 2, 18))])
    svc = service(provider)
    first = await svc.next(symbols("AAPL"))
    second = await svc.next(symbols("NVDA"))
    assert len(provider.calendar_calls) == 1
    assert first.rows[0].status == second.rows[0].status == "ok"
    assert json.loads(next(iter(redis.values.values())))["events"]


async def test_without_redis_every_request_calls_provider():
    provider = FakeProvider([event("AAPL", date(2027, 1, 28))])
    svc = service(provider)
    await svc.next(symbols("AAPL"))
    await svc.next(symbols("AAPL"))
    assert len(provider.calendar_calls) == 2


async def test_history_only_provider_is_501_without_call():
    provider = HistoryOnlyProvider()
    with pytest.raises(CapabilityNotSupportedError):
        await service(provider).next(symbols("AAPL"), "fake")
    assert provider.calendar_calls == []


async def test_history_only_provider_calendar_returns_reported_events():
    provider = HistoryOnlyProvider(
        history={"AAPL": [event("AAPL", date(2026, 10, 29), eps_actual="1.85", fiscal_period_end=date(2026, 9, 30))]},
    )
    result = await service(provider).calendar(symbols("AAPL"), date(2026, 1, 1), date(2027, 1, 1))
    assert provider.calendar_calls == [] and provider.history_calls == ["AAPL"]
    assert result.events[0].eps_actual == Decimal("1.85")
    assert result.symbols[0].history == "complete" and result.symbols[0].status == "ok"


async def test_history_budget_serves_request_order_then_pending():
    history = {s: [event(s, date(2026, 10, 29), eps_actual="1")] for s in "ABCDE"}
    provider = FakeProvider([event("A", date(2026, 12, 1))], history, budget=FakeBudget(3))
    result = await service(provider).calendar(
        symbols("A,B,C,D,E"), date(2026, 1, 1), date(2027, 1, 1)
    )
    assert len(provider.calendar_calls) == 1
    assert provider.history_calls == ["A", "B"]
    assert [(s.symbol, s.history) for s in result.symbols] == [
        ("A", "complete"), ("B", "complete"), ("C", "pending"), ("D", "pending"), ("E", "pending"),
    ]
    assert "budget" in result.symbols[2].message
    assert {e.symbol for e in result.events} == {"A", "B"}


async def test_quota_error_midway_keeps_earlier_symbols():
    history = {
        "A": [event("A", date(2026, 10, 29), eps_actual="1")],
        "B": ProviderQuotaExhaustedError("fake", "day", 25),
        "C": [event("C", date(2026, 10, 29), eps_actual="1")],
    }
    provider = FakeProvider(history=history)
    result = await service(provider).calendar(symbols("A,B,C"), date(2026, 1, 1), date(2026, 11, 1))
    assert provider.history_calls == ["A", "B"]
    assert [s.history for s in result.symbols] == ["complete", "pending", "pending"]
    assert [s.status for s in result.symbols] == ["ok", "ok", "ok"]


async def test_unknown_and_failing_symbols_get_statuses():
    provider = FakeProvider(history={"BAD": ProviderConnectionError("down")})
    result = await service(provider).calendar(
        symbols("ZZZ,BAD"), date(2026, 1, 1), date(2026, 11, 1)
    )
    assert [s.status for s in result.symbols] == ["not_found", "error"]
    assert result.symbols[1].message == "down"


async def test_all_failed_raises_provider_error():
    provider = FakeProvider(history={"A": ProviderConnectionError("down")})
    with pytest.raises(ProviderConnectionError):
        await service(provider).calendar(symbols("A"), date(2026, 1, 1), date(2026, 11, 1))
    failing = FakeProvider()
    failing.calendar_error = ProviderConnectionError("calendar down")
    with pytest.raises(ProviderConnectionError):
        await service(failing).next(symbols("AAPL"))
    with pytest.raises(ProviderConnectionError):
        await service(failing).calendar(symbols("AAPL"), TODAY, TODAY + timedelta(days=30))


async def test_calendar_failure_but_history_still_returns_ok_with_message():
    provider = FakeProvider(history={"A": [event("A", date(2026, 10, 29), eps_actual="1")]})
    provider.calendar_error = ProviderConnectionError("calendar down")
    result = await service(provider).calendar(symbols("A"), date(2026, 1, 1), date(2027, 1, 1))
    assert result.symbols[0].status == "ok" and "calendar unavailable" in result.symbols[0].message
    assert len(result.events) == 1


@pytest.mark.parametrize("start,end", [(TODAY, TODAY - timedelta(days=1)), (TODAY - timedelta(days=500), TODAY + timedelta(days=400))])
async def test_calendar_range_validation(start, end):
    with pytest.raises(DataValidationError):
        await service(FakeProvider()).calendar(symbols("AAPL"), start, end)


async def test_reconciliation_of_upcoming_and_reported_event():
    upcoming = event("AAPL", date(2027, 1, 28), fiscal_period_end=date(2026, 12, 31))
    reported = event("AAPL", date(2027, 1, 29), fiscal_period_end=date(2026, 12, 31), eps_actual="2.1")
    other = event("AAPL", date(2027, 4, 28), fiscal_period_end=date(2027, 3, 31))
    result = reconcile_events([upcoming, other, reported])
    assert [e.report_date for e in result] == [date(2027, 1, 29), date(2027, 4, 28)]
    assert result[0].eps_actual == Decimal("2.1")


async def test_calendar_endpoint_range_merges_upcoming_and_history_sorted():
    provider = FakeProvider(
        [event("MSFT", date(2027, 1, 27)), event("AAPL", date(2027, 1, 28))],
        {"AAPL": [event("AAPL", date(2026, 10, 29), eps_actual="1.85")]},
    )
    result = await service(provider).calendar(symbols("AAPL,MSFT"), date(2026, 10, 1), date(2027, 2, 28))
    assert [(e.report_date, e.symbol) for e in result.events] == [
        (date(2026, 10, 29), "AAPL"), (date(2027, 1, 27), "MSFT"), (date(2027, 1, 28), "AAPL"),
    ]
    assert len(provider.calendar_calls) == 1 and provider.history_calls == ["AAPL", "MSFT"]


async def test_company_earnings_etf_unknown_and_success():
    svc = service(FakeProvider(history={"AAPL": [event("AAPL", date(2026, 10, 29), eps_actual="1.85")]},
                              calendar=[event("AAPL", date(2027, 1, 28))]))
    with pytest.raises(CapabilityNotSupportedError) as etf:
        await svc.company(symbols("SPY")[0], date(2024, 1, 1), date(2027, 12, 31))
    assert etf.value.details["http_status"] == 422
    result = await svc.company(symbols("AAPL")[0], date(2024, 1, 1), date(2027, 12, 31))
    assert [e.report_date for e in result.events] == [date(2026, 10, 29), date(2027, 1, 28)]
    with pytest.raises(DataNotFoundError):
        await svc.company(symbols("ZZZZ")[0], date(2024, 1, 1), date(2027, 12, 31))


async def test_company_error_without_stored_data_is_raised():
    svc = service(FakeProvider(history={"AAPL": ProviderQuotaExhaustedError("fake", "day", 25)}))
    with pytest.raises(AppError) as error:
        await svc.company(symbols("AAPL")[0], date(2024, 1, 1), date(2027, 12, 31))
    assert error.value.code == "PROVIDER_QUOTA_EXHAUSTED"


async def test_data_as_of_is_oldest_involved_time(monkeypatch):
    provider = FakeProvider([event("AAPL", date(2027, 1, 28))], {"AAPL": [event("AAPL", date(2026, 10, 29), eps_actual="1")]})
    token = response_meta.begin()
    try:
        before = datetime.now(UTC)
        await service(provider).calendar(symbols("AAPL"), date(2026, 1, 1), date(2027, 2, 1))
        assert response_meta.current().data_as_of >= before
    finally:
        response_meta.end(token)


async def test_company_with_budget_used_up_before_any_call_is_429_not_404():
    provider = FakeProvider(budget=FakeBudget(0))
    with pytest.raises(ProviderQuotaExhaustedError) as error:
        await service(provider).company(symbols("GOOGL")[0], date(2024, 1, 1), date(2026, 12, 31))
    assert error.value.details["period"] == "day" and provider.history_calls == []


async def test_company_with_budget_used_up_keeps_calendar_events():
    provider = FakeProvider([event("NVDA", TODAY)], budget=FakeBudget(0))
    result = await service(provider).company(symbols("NVDA")[0], date(2024, 1, 1), date(2026, 12, 31))
    assert [e.report_date for e in result.events] == [TODAY]
    assert result.symbols[0].history == "pending"
