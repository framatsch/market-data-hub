"""Per-symbol upcoming providers (day window + per-symbol plan) with a real store."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import text

from app import response_meta
from app.models.earnings import EarningsEvent
from app.providers.base import BaseEarningsHistoryProvider, BaseEarningsUpcomingProvider
from app.providers.registry import ProviderRegistry
from app.services import earnings_service as module
from app.services.earnings_service import EarningsService, parse_symbol_list
from app.store import engine
from app.utils.errors import (
    DataNotFoundError,
    ProviderConnectionError,
    ProviderQuotaExhaustedError,
)

pytestmark = pytest.mark.integration
TODAY = date(2026, 11, 18)  # Wednesday


class Budget:
    def __init__(self, remaining):
        self.left = remaining

    async def remaining(self):
        return self.left

    async def usage(self):
        return {"day": {"budget": 100, "used": 100}, "month": {"budget": 1000, "used": 10}, "day_exhausted": False}


class SymbolProvider(BaseEarningsUpcomingProvider, BaseEarningsHistoryProvider):
    name = "earningsapi"
    upcoming_mode = "symbol"
    earnings_day_calendar = True

    def __init__(self, days=None, symbols=None, budget=None):
        self.days = days or {}
        self.symbols = symbols or {}
        self.budget = budget
        self.day_calls = []
        self.symbol_calls = []
        self.upcoming_calls = 0
        self.day_error = None

    async def get_upcoming_earnings(self, start, end, roots):
        self.upcoming_calls += 1
        raise AssertionError("never called for symbol providers")

    async def get_earnings_for_date(self, day):
        self.day_calls.append(day)
        if self.budget is not None:
            self.budget.left -= 1
        if self.day_error:
            raise self.day_error
        return list(self.days.get(day, []))

    async def get_symbol_earnings(self, root):
        self.symbol_calls.append(root)
        if self.budget is not None:
            self.budget.left -= 1
        if root not in self.symbols:
            raise DataNotFoundError("Earnings", root)
        return list(self.symbols[root])

    async def get_earnings_history(self, root):
        return [e for e in await self.get_symbol_earnings(root) if e.reported]

    async def test_connection(self):
        return {"success": True}


def ev(symbol, day, **kwargs):
    return EarningsEvent(symbol=symbol, report_date=day, provider="earningsapi", **kwargs)


def syms(text_):
    return parse_symbol_list(text_)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr("app.models.earnings.earnings_today", lambda: TODAY)
    monkeypatch.setattr(module, "earnings_today", lambda: TODAY)
    monkeypatch.setattr(module, "budget_redis", lambda: None)


def build(provider):
    registry = ProviderRegistry.__new__(ProviderRegistry)
    registry._providers = {"earningsapi": provider}
    registry.default_earnings_provider = "earningsapi"
    registry._provider_locks, registry._provider_inflight, registry._provider_drained = {}, {}, {}
    return EarningsService(registry)


async def request(call):
    token = response_meta.begin()
    try:
        return await call, response_meta.current()
    finally:
        response_meta.end(token)


WINDOW = [date(2026, 11, d) for d in (17, 18, 19, 20, 23, 24, 25, 26, 27)]


async def age_days(hours, scope_prefix="calendar-day:"):
    async with engine.session_scope() as session:
        await session.execute(
            text("UPDATE earnings_sync SET synced_at = :t WHERE scope LIKE :p"),
            {"t": datetime.now(UTC) - timedelta(hours=hours), "p": scope_prefix + "%"},
        )


async def age_symbol(scope, days):
    async with engine.session_scope() as session:
        await session.execute(
            text("UPDATE earnings_sync SET synced_at = :t WHERE scope = :s"),
            {"t": datetime.now(UTC) - timedelta(days=days), "s": scope},
        )


async def test_window_filled_then_answers_next_without_symbol_request(db):
    provider = SymbolProvider(days={date(2026, 11, 24): [ev("ADI", date(2026, 11, 24), report_time="bmo")]})
    svc = build(provider)
    result, meta = await request(svc.next(syms("ADI")))
    assert provider.day_calls == WINDOW and provider.symbol_calls == [] and provider.upcoming_calls == 0
    row = result.rows[0]
    assert row.status == "ok" and row.event.report_date == date(2026, 11, 24) and row.days_until == 6
    assert not meta.stale
    # Second request: everything is fresh.
    await request(svc.next(syms("ADI")))
    assert provider.day_calls == WINDOW and provider.symbol_calls == []


async def test_steady_state_refreshes_only_the_near_days(db):
    provider = SymbolProvider()
    svc = build(provider)
    await request(svc.next(syms("ADI")))
    provider.day_calls.clear()
    await age_days(24)
    await request(svc.next(syms("ADI")))
    assert provider.day_calls == [date(2026, 11, d) for d in (17, 18, 19, 20)]


async def test_actuals_from_previous_day_without_symbol_request(db):
    provider = SymbolProvider(days={
        date(2026, 11, 17): [ev("ADI", date(2026, 11, 17), eps_actual="3.5", eps_estimate="3.3")],
        date(2026, 11, 24): [ev("ADI", date(2026, 11, 24))],
    })
    svc = build(provider)
    result, _ = await request(svc.next(syms("ADI")))
    row = result.rows[0]
    assert str(row.last_reported.eps_actual) == "3.5" and row.event.report_date == date(2026, 11, 24)
    assert provider.symbol_calls == []


async def test_beyond_window_symbol_request_and_last_reported(db):
    provider = SymbolProvider(symbols={"NVDA": [
        ev("NVDA", date(2027, 2, 18)),
        ev("NVDA", date(2026, 8, 20), eps_actual="1.1"),
    ]})
    svc = build(provider)
    result, _ = await request(svc.next(syms("NVDA")))
    row = result.rows[0]
    assert provider.symbol_calls == ["NVDA"]
    assert row.event.report_date == date(2027, 2, 18) and row.last_reported.report_date == date(2026, 8, 20)
    await request(svc.next(syms("NVDA")))
    assert provider.symbol_calls == ["NVDA"]  # known next date: never refetched for age
    await age_symbol("NVDA", 60)
    await request(svc.next(syms("NVDA")))
    assert provider.symbol_calls == ["NVDA"]


async def test_date_not_announced_is_checked_weekly(db):
    provider = SymbolProvider(symbols={"AAPL": [ev("AAPL", date(2026, 11, 2), eps_actual="2")]})
    svc = build(provider)
    result, _ = await request(svc.next(syms("AAPL")))
    assert result.rows[0].status == "none_scheduled" and provider.symbol_calls == ["AAPL"]
    await age_symbol("AAPL", 3)
    await request(svc.next(syms("AAPL")))
    assert provider.symbol_calls == ["AAPL"]
    await age_symbol("AAPL", 8)
    await request(svc.next(syms("AAPL")))
    assert provider.symbol_calls == ["AAPL", "AAPL"]


async def test_budget_exhausted_serves_in_request_order(db):
    budget = Budget(9 + 1)  # nine window days, one symbol request
    provider = SymbolProvider(
        symbols={"ADI": [ev("ADI", date(2027, 2, 18))], "NVDA": [ev("NVDA", date(2027, 2, 19))]},
        budget=budget,
    )
    svc = build(provider)
    result, _ = await request(svc.next(syms("ADI,NVDA")))
    by = {r.symbol: r for r in result.rows}
    assert provider.symbol_calls == ["ADI"]
    assert by["ADI"].status == "ok"
    assert by["NVDA"].status == "error" and by["NVDA"].message == "provider request budget exhausted"


async def test_calendar_for_watchlist_requests_two_symbols(db):
    provider = SymbolProvider(symbols={
        "ADI": [ev("ADI", date(2027, 2, 18)), ev("ADI", date(2026, 8, 19), eps_actual="3")],
        "AAPL": [ev("AAPL", date(2027, 1, 28)), ev("AAPL", date(2026, 10, 29), eps_actual="1")],
    })
    svc = build(provider)
    await request(svc.next(syms("MSFT")))  # fills the window
    provider.symbol_calls.clear()
    result, _ = await request(svc.calendar(syms("ADI,AAPL,SPY"), date(2026, 1, 1), date(2027, 6, 1), None, "all"))
    assert sorted(provider.symbol_calls) == ["AAPL", "ADI"]
    assert [s.status for s in result.symbols] == ["ok", "ok", "not_applicable"]
    assert all(s.history == "complete" for s in result.symbols[:2])


async def test_kind_reported_requests_no_day_calendar(db):
    provider = SymbolProvider(symbols={"ADI": [ev("ADI", date(2027, 2, 18)), ev("ADI", date(2026, 8, 19), eps_actual="3")]})
    svc = build(provider)
    result = await svc.company(syms("ADI")[0], date(2025, 1, 1), date(2027, 6, 1), "earningsapi", "reported")
    assert provider.day_calls == [] and all(e.reported for e in result.events) and result.events
    upcoming = await svc.company(syms("ADI")[0], date(2025, 1, 1), date(2027, 6, 1), "earningsapi", "upcoming")
    assert all(not e.reported for e in upcoming.events) and upcoming.events
    assert upcoming.symbols[0].history == "not_requested"


async def test_day_failure_keeps_stored_data_and_marks_stale(db):
    provider = SymbolProvider(days={date(2026, 11, 24): [ev("ADI", date(2026, 11, 24))]})
    svc = build(provider)
    await request(svc.next(syms("ADI")))
    await age_days(30)
    provider.day_error = ProviderConnectionError("down")
    result, meta = await request(svc.next(syms("ADI")))
    assert result.rows[0].status == "ok" and meta.stale


async def test_moved_into_window_replaces_symbol_event(db, monkeypatch):
    provider = SymbolProvider(symbols={"ADI": [ev("ADI", date(2026, 12, 9))]})
    svc = build(provider)
    # Beyond the window (it ends 2026-11-27): the per-symbol request stores 2026-12-09.
    result, _ = await request(svc.next(syms("ADI")))
    assert result.rows[0].event.report_date == date(2026, 12, 9)
    # A day later the window reaches 2026-11-30, whose calendar now lists ADI.
    provider.days[date(2026, 11, 30)] = [ev("ADI", date(2026, 11, 30))]
    monkeypatch.setattr("app.models.earnings.earnings_today", lambda: date(2026, 11, 19))
    monkeypatch.setattr(module, "earnings_today", lambda: date(2026, 11, 19))
    result, _ = await request(svc.next(syms("ADI")))
    assert result.rows[0].event.report_date == date(2026, 11, 30)
    assert provider.symbol_calls == ["ADI"]


async def test_kind_reported_refreshes_after_the_report(db, monkeypatch):
    provider = SymbolProvider(symbols={"ADI": [ev("ADI", date(2026, 11, 24)), ev("ADI", date(2026, 8, 19), eps_actual="3")]})
    svc = build(provider)
    await svc.company(syms("ADI")[0], date(2025, 1, 1), date(2027, 6, 1), "earningsapi", "reported")
    assert provider.symbol_calls == ["ADI"]
    # ADI reported on 2026-11-24; two days later a reported-only request picks up the actual.
    provider.symbols["ADI"] = [
        ev("ADI", date(2026, 11, 24), eps_actual="4.1"), ev("ADI", date(2026, 8, 19), eps_actual="3"),
    ]
    later = date(2026, 11, 26)
    monkeypatch.setattr("app.models.earnings.earnings_today", lambda: later)
    monkeypatch.setattr(module, "earnings_today", lambda: later)
    result = await svc.company(syms("ADI")[0], date(2025, 1, 1), date(2027, 6, 1), "earningsapi", "reported")
    assert provider.symbol_calls == ["ADI", "ADI"] and provider.day_calls == []
    latest = max(result.events, key=lambda e: e.report_date)
    assert latest.report_date == date(2026, 11, 24) and str(latest.eps_actual) == "4.1"


async def test_quota_signal_in_window_marks_symbols_budget_exhausted(db):
    provider = SymbolProvider(symbols={"NVDA": [ev("NVDA", date(2027, 2, 19))]})
    svc = build(provider)
    await request(svc.next(syms("NVDA")))  # window and NVDA stored
    await age_days(30)
    provider.day_calls.clear()
    provider.symbol_calls.clear()
    provider.day_error = ProviderQuotaExhaustedError("earningsapi", "day", 100)
    result, meta = await request(svc.next(syms("NVDA,ADI")))
    by = {r.symbol: r for r in result.rows}
    assert len(provider.day_calls) == 1 and provider.symbol_calls == []
    assert by["NVDA"].status == "ok"
    assert by["ADI"].status == "error" and by["ADI"].message == "provider request budget exhausted"
    assert meta.stale
