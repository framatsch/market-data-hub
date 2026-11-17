"""Earnings store against a real PostgreSQL (skipped when none is reachable)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.earnings import EarningsEvent
from app.store import earnings_repository as repo
from app.store import engine
from app.store.models import EarningsEventRow

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 17, 15, tzinfo=UTC)
START, END = date(2026, 11, 17), date(2027, 5, 27)


def event(symbol, report_date, provider="alphavantage", **kwargs) -> EarningsEvent:
    return EarningsEvent(
        symbol=symbol, report_date=report_date, provider=provider, **kwargs
    )


async def calendar(events, provider="alphavantage", start=START, end=END, now=NOW):
    async with engine.session_scope() as session:
        await repo.replace_calendar(session, provider, events, start, end, now)


async def read(symbols=None, provider="alphavantage", start=date(2020, 1, 1), end=END):
    async with engine.session_scope() as session:
        return await repo.read_events(session, provider, symbols, start, end)


async def test_moved_report_date_replaces_old_row(db):
    await calendar([event("AAPL", date(2027, 1, 28)), event("MSFT", date(2027, 1, 27))])
    await calendar([event("AAPL", date(2027, 1, 30)), event("MSFT", date(2027, 1, 27))])
    aapl = await read(["AAPL"])
    assert [e.report_date for e in aapl] == [date(2027, 1, 30)]
    assert len(await read()) == 2


async def test_calendar_stores_unrequested_symbols_and_state(db):
    await calendar([event(f"S{i}", date(2027, 1, 1) + timedelta(days=i % 20)) for i in range(4000)])
    async with engine.session_scope() as session:
        sync = await repo.get_sync(session, "alphavantage", "calendar")
    assert len(await read(["S1234"])) == 1
    assert sync.covered_from == START and sync.covered_to == END and sync.synced_at == NOW
    assert sync.sync_failed_at is None


async def test_replace_only_touches_covered_range_and_calendar_source(db):
    await calendar([event("AAPL", date(2026, 12, 1)), event("MSFT", date(2027, 5, 1))])
    async with engine.session_scope() as session:
        await repo.upsert_history(session, "alphavantage", "AAPL", [
            event("AAPL", date(2026, 12, 2), eps_actual=Decimal("1.2"),
                  fiscal_period_end=date(2026, 9, 30)),
        ], NOW)
    await calendar([], start=date(2026, 11, 17), end=date(2026, 12, 31))
    rows = {(e.symbol, e.report_date) for e in await read()}
    assert rows == {("AAPL", date(2026, 12, 2)), ("MSFT", date(2027, 5, 1))}


async def test_history_reconciles_calendar_row_for_same_period(db):
    period = date(2026, 12, 31)
    await calendar([event("AAPL", date(2027, 1, 28), fiscal_period_end=period)])
    async with engine.session_scope() as session:
        await repo.upsert_history(session, "alphavantage", "AAPL", [
            event("AAPL", date(2027, 1, 29), fiscal_period_end=period,
                  eps_actual=Decimal("2.1"), reported=True, report_time="amc"),
        ], NOW)
    rows = await read(["AAPL"])
    assert len(rows) == 1
    assert rows[0].report_date == date(2027, 1, 29) and rows[0].eps_actual == Decimal("2.1")
    # A later calendar sync cannot resurrect the reconciled quarter.
    await calendar([event("AAPL", date(2027, 1, 28), fiscal_period_end=period)])
    assert [e.report_date for e in await read(["AAPL"])] == [date(2027, 1, 29)]


async def test_history_without_actual_keeps_calendar_row(db):
    period = date(2026, 12, 31)
    await calendar([event("AAPL", date(2027, 1, 28), fiscal_period_end=period)])
    async with engine.session_scope() as session:
        await repo.upsert_history(session, "alphavantage", "AAPL", [
            event("AAPL", date(2026, 10, 29), fiscal_period_end=date(2026, 9, 30)),
        ], NOW)
    assert len(await read(["AAPL"])) == 2


async def test_history_upsert_preserves_first_seen_and_updates_values(db):
    old = event("AAPL", date(2026, 10, 29), eps_actual=Decimal("1.0"))
    async with engine.session_scope() as session:
        await repo.upsert_history(session, "alphavantage", "AAPL", [old], NOW)
        await repo.upsert_history(session, "alphavantage", "AAPL", [
            event("AAPL", date(2026, 10, 29), eps_actual=Decimal("1.5"), report_time="amc"),
        ], NOW + timedelta(hours=13))
        row = await session.get(EarningsEventRow, ("alphavantage", "AAPL", date(2026, 10, 29)))
    assert row.first_seen_at == NOW and row.updated_at == NOW + timedelta(hours=13)
    assert row.eps_actual == Decimal("1.5") and row.report_time == "amc"
    assert row.source == "history"


async def test_provider_isolation_and_clear(db):
    await calendar([event("AAPL", date(2027, 1, 28))], "alphavantage")
    await calendar([event("AAPL", date(2027, 1, 29), provider="other")], "other")
    assert [e.report_date for e in await read(["AAPL"], "alphavantage")] == [date(2027, 1, 28)]
    assert [e.report_date for e in await read(["AAPL"], "other")] == [date(2027, 1, 29)]
    await calendar([], "alphavantage")
    assert await read(["AAPL"], "alphavantage") == []
    assert len(await read(["AAPL"], "other")) == 1
    async with engine.session_scope() as session:
        assert await repo.clear(session, "other") == 1
    assert await read(None, "other") == []


async def test_failed_state_does_not_lose_success_time(db):
    await calendar([event("AAPL", date(2027, 1, 28))])
    async with engine.session_scope() as session:
        await repo.mark_failed(session, "alphavantage", "calendar", NOW + timedelta(minutes=5))
        sync = await repo.get_sync(session, "alphavantage", "calendar")
        states = await repo.get_syncs(session, "alphavantage", ["calendar", "AAPL"])
    assert sync.synced_at == NOW and sync.sync_failed_at == NOW + timedelta(minutes=5)
    assert set(states) == {"calendar"}
