"""Earnings service with the PostgreSQL store (skipped when none is reachable)."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import text

from app import response_meta
from app.models.earnings import EarningsEvent
from app.providers.base import BaseEarningsHistoryProvider, BaseEarningsUpcomingProvider
from app.providers.registry import ProviderRegistry
from app.services import earnings_service as module
from app.services.earnings_service import EarningsService, parse_symbol_list
from app.store import earnings_repository as repo
from app.store import engine
from app.utils.errors import (
    DataNotFoundError,
    ProviderConnectionError,
    ProviderQuotaExhaustedError,
)

pytestmark = pytest.mark.integration
TODAY = date(2026, 11, 17)


class Fake(BaseEarningsUpcomingProvider, BaseEarningsHistoryProvider):
    name = "fake"

    def __init__(self, calendar=(), history=None):
        self.calendar = list(calendar)
        self.history = history or {}
        self.calendar_calls = 0
        self.history_calls = []
        self.calendar_error = None
        self.history_error = None

    async def get_upcoming_earnings(self, start, end, roots):
        self.calendar_calls += 1
        if self.calendar_error:
            raise self.calendar_error
        return list(self.calendar)

    async def get_earnings_history(self, root):
        self.history_calls.append(root)
        if self.history_error:
            raise self.history_error
        if root not in self.history:
            raise DataNotFoundError("Earnings", root)
        return list(self.history[root])

    async def test_connection(self):
        return {"success": True}


def ev(symbol, day, **kwargs):
    return EarningsEvent(symbol=symbol, report_date=day, provider="fake", **kwargs)


def syms(text_):
    return parse_symbol_list(text_)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr("app.models.earnings.earnings_today", lambda: TODAY)
    monkeypatch.setattr(module, "earnings_today", lambda: TODAY)
    monkeypatch.setattr(module, "budget_redis", lambda: None)


def build(provider):
    registry = ProviderRegistry.__new__(ProviderRegistry)
    registry._providers = {"fake": provider}
    registry.default_earnings_provider = "fake"
    registry._provider_locks, registry._provider_inflight, registry._provider_drained = {}, {}, {}
    return EarningsService(registry)


async def request(call):
    token = response_meta.begin()
    try:
        result = await call
        return result, response_meta.current()
    finally:
        response_meta.end(token)


async def age(scope, **interval):
    column = "synced_at"
    async with engine.session_scope() as session:
        await session.execute(
            text(f"UPDATE earnings_sync SET {column} = :t WHERE scope = :scope"),
            {"t": datetime.now(UTC) - timedelta(**interval), "scope": scope},
        )


async def test_fresh_store_serves_unrequested_symbols_without_provider(db):
    provider = Fake([ev("AAPL", date(2027, 1, 28)), ev("NVDA", date(2027, 2, 18))])
    svc = build(provider)
    first, _ = await request(svc.next(syms("AAPL")))
    second, second_meta = await request(svc.next(syms("NVDA")))
    assert provider.calendar_calls == 1
    assert first.rows[0].status == second.rows[0].status == "ok"
    assert not second_meta.stale and second_meta.data_as_of is not None


async def test_moved_report_date_after_resync(db):
    provider = Fake([ev("AAPL", date(2027, 1, 28))])
    svc = build(provider)
    await svc.next(syms("AAPL"))
    provider.calendar = [ev("AAPL", date(2027, 1, 30))]
    await age("calendar", hours=25)
    result, _ = await request(svc.next(syms("AAPL")))
    assert result.rows[0].event.report_date == date(2027, 1, 30)
    assert provider.calendar_calls == 2


async def test_stale_serving_and_retry_pause_on_failure(db):
    provider = Fake([ev("AAPL", date(2027, 1, 28))])
    svc = build(provider)
    await svc.next(syms("AAPL"))
    await age("calendar", hours=30)
    provider.calendar_error = ProviderQuotaExhaustedError("fake", "day", 25)
    result, meta = await request(svc.next(syms("AAPL")))
    assert result.rows[0].event.report_date == date(2027, 1, 28)
    assert meta.stale and meta.stale_reason == "PROVIDER_QUOTA_EXHAUSTED"
    assert provider.calendar_calls == 2
    again, again_meta = await request(svc.next(syms("AAPL")))  # inside the retry pause
    assert provider.calendar_calls == 2 and again.rows[0].status == "ok"
    assert again_meta.stale and again_meta.stale_reason == "PROVIDER_ERROR"


async def test_history_fetched_once_then_stored_and_actuals_window(db):
    provider = Fake(history={"AAPL": [ev("AAPL", TODAY - timedelta(days=2), fiscal_period_end=date(2026, 9, 30))]})
    svc = build(provider)
    start, end = date(2026, 1, 1), TODAY + timedelta(days=30)
    await svc.calendar(syms("AAPL"), start, end)
    await svc.calendar(syms("AAPL"), start, end)
    assert provider.history_calls == ["AAPL"]
    await age("AAPL", hours=13)  # reported two days ago, still no actual EPS
    await svc.calendar(syms("AAPL"), start, end)
    assert provider.history_calls == ["AAPL", "AAPL"]


async def test_history_failure_serves_stored_events_stale(db):
    provider = Fake(history={"AAPL": [ev("AAPL", TODAY - timedelta(days=2), eps_actual="1.5")]})
    svc = build(provider)
    start, end = date(2026, 1, 1), TODAY + timedelta(days=30)
    await svc.calendar(syms("AAPL"), start, end)
    await age("AAPL", hours=13)
    async with engine.session_scope() as session:  # event lost its actual: due again
        await session.execute(text("UPDATE earnings_events SET eps_actual = NULL"))
    provider.history_error = ProviderConnectionError("down")
    result, meta = await request(svc.calendar(syms("AAPL"), start, end))
    assert len(result.events) == 1 and meta.stale
    assert result.symbols[0].status == "ok"


async def test_next_reports_last_reported_from_store(db):
    provider = Fake([ev("AAPL", date(2027, 1, 28))], {"AAPL": [ev("AAPL", date(2026, 10, 29), eps_actual="1.85")]})
    svc = build(provider)
    await svc.calendar(syms("AAPL"), date(2026, 1, 1), date(2027, 3, 1))
    result, _ = await request(svc.next(syms("AAPL")))
    assert result.rows[0].last_reported.report_date == date(2026, 10, 29)
    assert result.rows[0].event.report_date == date(2027, 1, 28)
    assert provider.history_calls == ["AAPL"]  # next itself never fetched history


async def test_unknown_symbol_is_not_found_and_not_refetched(db):
    provider = Fake()
    svc = build(provider)
    start, end = date(2026, 1, 1), TODAY + timedelta(days=30)
    first = await svc.calendar(syms("ZZZZ"), start, end)
    second = await svc.calendar(syms("ZZZZ"), start, end)
    assert first.symbols[0].status == second.symbols[0].status == "not_found"
    assert provider.history_calls == ["ZZZZ"]


async def test_database_error_fails_open_to_provider(db, monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError("database unreachable")

    monkeypatch.setattr(repo, "read_events", broken)
    provider = Fake([ev("AAPL", date(2027, 1, 28))])
    result, meta = await request(build(provider).next(syms("AAPL")))
    assert result.rows[0].status == "ok" and provider.calendar_calls == 1
    assert not meta.stale
    assert not engine.store_usable()  # cooldown: later requests skip the store


async def test_calendar_failure_without_stored_data_raises(db):
    provider = Fake()
    provider.calendar_error = ProviderConnectionError("down")
    with pytest.raises(ProviderConnectionError):
        await build(provider).next(syms("AAPL"))
