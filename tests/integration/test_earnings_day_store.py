"""Day-calendar and per-symbol replacement rules against a real PostgreSQL."""

from datetime import UTC, date, datetime

import pytest

from app.models.earnings import EarningsEvent
from app.store import earnings_repository as repo
from app.store import engine

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 18, 15, tzinfo=UTC)
TODAY = date(2026, 11, 18)
P = "earningsapi"


def event(symbol, day, provider=P, **kwargs):
    return EarningsEvent(symbol=symbol, report_date=day, provider=provider, **kwargs)


async def day(d, events, provider=P):
    async with engine.session_scope() as session:
        await repo.replace_day(session, provider, d, events, TODAY, NOW)


async def symbol(root, events, provider=P):
    async with engine.session_scope() as session:
        await repo.upsert_history(session, provider, root, events, NOW, prune_upcoming_from=TODAY)


async def read(symbols=None, provider=P):
    async with engine.session_scope() as session:
        return await repo.read_events(session, provider, symbols, date(2020, 1, 1), date(2028, 1, 1))


async def sync(scope, provider=P):
    async with engine.session_scope() as session:
        return await repo.get_sync(session, provider, scope)


async def test_moved_into_window_drops_the_per_symbol_event(db):
    await symbol("ADI", [event("ADI", date(2026, 12, 9))])
    await day(date(2026, 11, 24), [event("ADI", date(2026, 11, 24)), event("AAPL", date(2026, 11, 24))])
    adi = await read(["ADI"])
    assert [e.report_date for e in adi] == [date(2026, 11, 24)]
    scope = await sync(repo.day_scope(date(2026, 11, 24)))
    assert scope.covered_from == scope.covered_to == date(2026, 11, 24) and scope.synced_at == NOW


async def test_moved_out_of_window_invalidates_symbol_sync(db):
    await symbol("ADI", [event("ADI", date(2027, 2, 18))])
    await day(date(2026, 11, 24), [event("ADI", date(2026, 11, 24))])
    assert (await sync("ADI")).invalidated_at is None
    await day(date(2026, 11, 24), [event("AAPL", date(2026, 11, 24))])
    # The event of the day is gone; the far-away per-symbol event (> 60 days) stays.
    assert {(e.symbol, e.report_date) for e in await read()} == {("AAPL", date(2026, 11, 24)), ("ADI", date(2027, 2, 18))}
    assert (await sync("ADI")).invalidated_at == NOW


async def test_moved_at_per_symbol_request_and_invalidation_cleared(db):
    await symbol("ADI", [event("ADI", date(2027, 2, 18))])
    await day(date(2026, 11, 24), [event("ADI", date(2026, 11, 24))])
    await day(date(2026, 11, 24), [])
    assert (await sync("ADI")).invalidated_at is not None
    await symbol("ADI", [event("ADI", date(2027, 2, 24)), event("ADI", date(2026, 8, 19), eps_actual=1)])
    adi = await read(["ADI"])
    assert [e.report_date for e in adi] == [date(2026, 8, 19), date(2027, 2, 24)]
    assert (await sync("ADI")).invalidated_at is None


async def test_day_replacement_is_authoritative_and_isolated(db):
    await day(date(2026, 11, 24), [event("ADI", date(2026, 11, 24)), event("OLD", date(2026, 11, 24))])
    await day(date(2026, 11, 24), [event("ADI", date(2026, 11, 24), report_time="bmo")])
    rows = await read()
    assert [(e.symbol, e.report_time) for e in rows] == [("ADI", "bmo")]
    await day(date(2026, 11, 24), [event("ADI", date(2026, 11, 24))], provider="alphavantage")
    assert len(await read()) == 1 and len(await read(provider="alphavantage")) == 1


async def test_reported_and_old_events_are_kept(db):
    await symbol("ADI", [event("ADI", date(2026, 8, 19), eps_actual=3.45)])
    await day(date(2026, 11, 24), [event("ADI", date(2026, 11, 24))])
    assert {e.report_date for e in await read(["ADI"])} == {date(2026, 8, 19), date(2026, 11, 24)}
