"""History store against a real PostgreSQL (skipped when none is reachable)."""

import asyncio
import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.config import settings
from app.models.price import PriceBar
from app.models.volatility import VolatilityPoint
from app.store import engine, repository
from app.store.migrate import ensure_schema
from app.store.repository import SeriesKey
from app.store.sync import HistorySync, Loaded, Profile
from app.utils.errors import (
    ProviderConnectionError,
    ProviderNotEntitledError,
    ProviderTimeoutError,
)

URL = os.getenv(
    "TEST_DATABASE_URL", "postgresql://mdh:mdh@localhost:55432/mdh_test"
)
pytestmark = pytest.mark.integration

WED_SESSION = datetime(2026, 11, 11, 16, 0, tzinfo=UTC)  # Wed 11:00 ET
WED_EVENING = datetime(2026, 11, 11, 21, 45, tzinfo=UTC)  # Wed 16:45 ET
SATURDAY = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


async def _drop_all(eng):
    async with eng.begin() as conn:
        await conn.execute(
            text(
                "DROP TABLE IF EXISTS earnings_events, earnings_sync, "
                "iv_points_daily, price_bars, "
                "history_series, alembic_version CASCADE"
            )
        )


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(settings, "HISTORY_STORE_RESYNC_SECONDS", 300)
    monkeypatch.setattr(settings, "HISTORY_STORE_OVERLAP_BARS", 5)


def bar(day: date, close: str = "100", volume: int = 10, provider: str = "ibkr") -> PriceBar:
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    value = Decimal(close)
    return PriceBar(
        symbol="AAPL",
        start=start,
        end=start,
        open=value,
        high=value + 1,
        low=value - 1,
        close=value,
        volume=volume,
        provider=provider,
        source_instrument="AAPL.US",
    )


def weekdays(first: date, last: date) -> list[date]:
    days = []
    while first <= last:
        if first.weekday() < 5:
            days.append(first)
        first += timedelta(days=1)
    return days


class FakeProvider:
    """Daily bars by date; records every requested range."""

    def __init__(self, first: date, last: date, close: str = "100") -> None:
        self.bars = {d: bar(d, close) for d in weekdays(first, last)}
        self.calls: list[tuple[datetime, datetime]] = []
        self.error: Exception | None = None
        self.missing: set[date] = set()

    async def __call__(self, start: datetime, end: datetime) -> Loaded[PriceBar]:
        self.calls.append((start, end))
        if self.error:
            raise self.error
        items = [
            b
            for d, b in sorted(self.bars.items())
            if start.date() <= d <= end.date() and d not in self.missing
        ]
        return Loaded(items=items, source_instrument="AAPL.US")


KEY = SeriesKey("prices", "AAPL", "ibkr", "1d")
PROFILE = Profile("prices", "1d")


async def serve(sync, provider, start, end, now, key=KEY, profile=PROFILE, **kw):
    return await sync.serve(key, profile, start, end, provider, now=now, **kw)


def d(year, month, day):
    return datetime(year, month, day, tzinfo=UTC)


async def test_first_load_then_stored_while_settled(db):
    sync, prov = HistorySync(), FakeProvider(date(2026, 10, 1), date(2026, 11, 13))
    first = await serve(sync, prov, d(2026, 10, 1), SATURDAY, SATURDAY)
    assert first.result == "full_load" and len(prov.calls) == 1
    assert first.items[-1].start.date() == date(2026, 11, 13)
    second = await serve(sync, prov, d(2026, 10, 1), SATURDAY, SATURDAY + timedelta(hours=1))
    assert second.result == "store" and len(prov.calls) == 1
    assert [b.close for b in second.items] == [b.close for b in first.items]
    assert second.data_as_of == SATURDAY


async def test_narrower_range_and_holiday_gap(db):
    sync, prov = HistorySync(), FakeProvider(date(2026, 10, 1), date(2026, 11, 13))
    prov.missing = {date(2026, 11, 11)}
    await serve(sync, prov, d(2026, 10, 1), SATURDAY, SATURDAY)
    narrow = await serve(sync, prov, d(2026, 11, 9), d(2026, 11, 13), SATURDAY)
    assert len(prov.calls) == 1
    assert date(2026, 11, 11) not in [b.start.date() for b in narrow.items]
    assert len(narrow.items) == 4


async def test_forming_bar_is_returned_not_stored(db):
    sync, prov = HistorySync(), FakeProvider(date(2026, 10, 1), date(2026, 11, 11))
    result = await serve(sync, prov, d(2026, 10, 1), WED_SESSION, WED_SESSION)
    assert result.items[-1].start.date() == date(2026, 11, 11)
    async with engine.session_scope() as s:
        series = await repository.get_series(s, KEY)
        stored = await repository.read_bars(s, series, d(2026, 10, 1), WED_SESSION)
    assert stored[-1].start.date() == date(2026, 11, 10)
    assert series.covered_to == d(2026, 11, 10)


async def test_after_settle_the_day_is_stored(db):
    sync, prov = HistorySync(), FakeProvider(date(2026, 10, 1), date(2026, 11, 11))
    await serve(sync, prov, d(2026, 10, 1), WED_EVENING, WED_EVENING)
    async with engine.session_scope() as s:
        series = await repository.get_series(s, KEY)
        stored = await repository.read_bars(s, series, d(2026, 10, 1), WED_EVENING)
    assert stored[-1].start.date() == date(2026, 11, 11)


async def test_tail_only_loads_overlap(db):
    sync, prov = HistorySync(), FakeProvider(date(2026, 10, 1), date(2026, 11, 13))
    await serve(sync, prov, d(2026, 10, 1), WED_SESSION, WED_SESSION)
    later = WED_SESSION + timedelta(minutes=10)
    result = await serve(sync, prov, d(2026, 10, 1), later, later)
    assert len(prov.calls) == 2
    # Five newest stored bars: Nov 4..10
    assert prov.calls[1][0].date() == date(2026, 11, 4)
    assert result.result == "tail_sync"


async def test_resync_interval_throttles_and_no_cache_forces(db):
    sync, prov = HistorySync(), FakeProvider(date(2026, 10, 1), date(2026, 11, 13))
    await serve(sync, prov, d(2026, 10, 1), WED_SESSION, WED_SESSION)
    soon = WED_SESSION + timedelta(seconds=60)
    await serve(sync, prov, d(2026, 10, 2), soon, soon)
    assert len(prov.calls) == 1
    await serve(sync, prov, d(2026, 10, 2), soon, soon, force=True)
    assert len(prov.calls) == 2


async def test_parallel_requests_share_one_call(db):
    sync, prov = HistorySync(), FakeProvider(date(2026, 10, 1), date(2026, 11, 13))
    results = await asyncio.gather(
        *[serve(sync, prov, d(2026, 10, 1), SATURDAY, SATURDAY) for _ in range(10)]
    )
    assert len(prov.calls) == 1
    assert len({len(r.items) for r in results}) == 1


async def test_backfill_loads_only_the_earlier_range(db):
    sync, prov = HistorySync(), FakeProvider(date(2026, 1, 1), date(2026, 11, 13))
    await serve(sync, prov, d(2026, 10, 1), SATURDAY, SATURDAY)
    result = await serve(sync, prov, d(2026, 9, 1), SATURDAY, SATURDAY)
    assert result.result == "backfill"
    assert prov.calls[1][0] == d(2026, 9, 1) and prov.calls[1][1].date() <= date(2026, 10, 2)
    assert result.items[0].start.date() == date(2026, 9, 1)
    again = await serve(sync, prov, d(2026, 9, 1), SATURDAY, SATURDAY)
    assert again.result == "store" and len(prov.calls) == 2


async def test_split_reloads_whole_series(db):
    sync, prov = HistorySync(), FakeProvider(date(2026, 10, 1), date(2026, 11, 13), "400")
    await serve(sync, prov, d(2026, 10, 1), WED_SESSION, WED_SESSION)
    prov.bars = {k: bar(k, "100") for k in prov.bars}
    later = WED_SESSION + timedelta(hours=1)
    result = await serve(sync, prov, d(2026, 10, 1), later, later)
    assert result.result == "reload"
    assert {b.close for b in result.items if b.start.date() < date(2026, 11, 11)} == {Decimal(100)}


async def test_newest_bar_correction_and_volume_do_not_reload(db):
    sync, prov = HistorySync(), FakeProvider(date(2026, 10, 1), date(2026, 11, 13))
    await serve(sync, prov, d(2026, 10, 1), SATURDAY, SATURDAY)
    prov.bars[date(2026, 11, 13)] = bar(date(2026, 11, 13), "105")
    prov.bars[date(2026, 11, 12)] = bar(date(2026, 11, 12), "100", volume=999)
    # Monday: tail due again
    monday = d(2026, 11, 16) + timedelta(hours=23)
    prov.bars[date(2026, 11, 16)] = bar(date(2026, 11, 16))
    result = await serve(sync, prov, d(2026, 10, 1), monday, monday)
    assert result.result == "tail_sync"
    by_day = {b.start.date(): b for b in result.items}
    assert by_day[date(2026, 11, 13)].close == Decimal(105)
    assert by_day[date(2026, 11, 12)].volume == 999


async def test_reload_failure_keeps_rows(db):
    sync, prov = HistorySync(), FakeProvider(date(2026, 10, 1), date(2026, 11, 13), "400")
    await serve(sync, prov, d(2026, 10, 1), WED_SESSION, WED_SESSION)
    prov.bars = {k: bar(k, "100") for k in prov.bars}
    calls = {"n": 0}
    original = prov.__call__

    async def flaky(start, end):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ProviderTimeoutError("ibkr")
        return await original(start, end)

    later = WED_SESSION + timedelta(hours=1)
    result = await sync.serve(KEY, PROFILE, d(2026, 10, 1), later, flaky, now=later)
    assert result.stale and result.stale_reason == "PROVIDER_TIMEOUT"
    assert {b.close for b in result.items} == {Decimal(400)}


async def test_stale_on_failure_then_throttled(db):
    sync, prov = HistorySync(), FakeProvider(date(2026, 10, 1), date(2026, 11, 13))
    await serve(sync, prov, d(2026, 10, 1), WED_SESSION, WED_SESSION)
    prov.error = ProviderConnectionError("down")
    later = WED_SESSION + timedelta(minutes=10)
    result = await serve(sync, prov, d(2026, 10, 1), later, later)
    assert result.stale and result.stale_reason == "PROVIDER_CONNECTION_ERROR"
    assert result.items[-1].start.date() == date(2026, 11, 10)
    calls = len(prov.calls)
    for _ in range(4):
        again = await serve(sync, prov, d(2026, 10, 1), later, later + timedelta(seconds=5))
        assert again.stale
    assert len(prov.calls) == calls


async def test_failure_without_store_and_not_entitled_raise(db):
    sync, prov = HistorySync(), FakeProvider(date(2026, 10, 1), date(2026, 11, 13))
    prov.error = ProviderConnectionError("down")
    early = WED_SESSION - timedelta(days=1)
    with pytest.raises(ProviderConnectionError):
        await serve(sync, prov, d(2026, 10, 1), early, early)
    ok = FakeProvider(date(2026, 10, 1), date(2026, 11, 13))
    await serve(sync, ok, d(2026, 10, 1), WED_SESSION, WED_SESSION)
    ok.error = ProviderNotEntitledError("ibkr", symbol="AAPL")
    later = WED_SESSION + timedelta(hours=1)
    with pytest.raises(ProviderNotEntitledError):
        await serve(sync, ok, d(2026, 10, 1), later, later)


async def test_providers_are_isolated(db):
    sync = HistorySync()
    a = FakeProvider(date(2026, 10, 1), date(2026, 11, 13), "100")
    b = FakeProvider(date(2026, 10, 1), date(2026, 11, 13), "200")
    await serve(sync, a, d(2026, 10, 1), SATURDAY, SATURDAY)
    other = SeriesKey("prices", "AAPL", "schwab", "1d")
    res = await serve(sync, b, d(2026, 10, 1), SATURDAY, SATURDAY, key=other)
    assert {x.close for x in res.items} == {Decimal(200)}
    assert len(b.calls) == 1


async def test_weekly_series_stores_closed_weeks_only(db):
    sync = HistorySync()
    key, profile = SeriesKey("prices", "AAPL", "ibkr", "1w"), Profile("prices", "1w")

    async def weekly(start, end):
        mondays = [d(2026, 10, 26), d(2026, 11, 2), d(2026, 11, 9)]
        items = [bar(m.date()) for m in mondays if start <= m + timedelta(days=6) and m <= end]
        return Loaded(items=items)

    res = await sync.serve(key, profile, d(2026, 11, 4), WED_SESSION, weekly, now=WED_SESSION)
    # week of Nov 2 contains start; running week Nov 9 is returned but not stored
    assert [b.start.date() for b in res.items] == [date(2026, 11, 2), date(2026, 11, 9)]
    async with engine.session_scope() as s:
        series = await repository.get_series(s, key)
        stored = await repository.read_bars(s, series, d(2026, 10, 1), WED_SESSION)
    assert [b.start.date() for b in stored] == [date(2026, 11, 2)]


async def test_hourly_series_forming_bar_and_rth_evening(db):
    sync = HistorySync()
    key, profile = SeriesKey("prices", "AAPL", "ibkr", "1h"), Profile("prices", "1h")
    now = datetime(2026, 11, 11, 16, 20, tzinfo=UTC)  # 11:20 ET

    def hour(h):
        start = datetime(2026, 11, 11, h, tzinfo=UTC)
        return bar(date(2026, 11, 11)).model_copy(update={"start": start, "end": start})

    async def hourly(start, end):
        return Loaded(items=[hour(h) for h in range(14, 17)])  # 09:00..11:00 ET

    res = await sync.serve(key, profile, datetime(2026, 11, 11, tzinfo=UTC), now, hourly, now=now)
    assert len(res.items) == 3
    async with engine.session_scope() as s:
        series = await repository.get_series(s, key)
        stored = await repository.read_bars(s, series, datetime(2026, 11, 10, tzinfo=UTC), now)
    assert [b.start.hour for b in stored] == [14, 15]
    evening = datetime(2026, 11, 12, 0, 0, tzinfo=UTC)  # Wed 19:00 ET

    async def full(start, end):
        return Loaded(items=[hour(h) for h in range(14, 21)])

    await sync.serve(key, profile, datetime(2026, 11, 11, tzinfo=UTC), evening, full, now=evening)
    calls = []

    async def spy(start, end):
        calls.append(1)
        return Loaded(items=[])

    later = evening + timedelta(minutes=30)
    await sync.serve(
        key, profile, datetime(2026, 11, 11, 14, tzinfo=UTC), later, spy, now=later
    )
    assert calls == []


def point(day: date, iv: str = "0.25") -> VolatilityPoint:
    return VolatilityPoint(date=day, iv=Decimal(iv))


async def test_iv_not_yet_published_keeps_tail_due(db):
    sync = HistorySync()
    key, profile = SeriesKey("iv", "AAPL", "lseg", "1d", False, 30, ""), Profile("iv", "1d")
    thursday = datetime(2026, 11, 12, 22, 0, tzinfo=UTC)  # Thu 17:00 ET
    calls = []

    async def loader(start, end):
        calls.append(start)
        return Loaded(items=[point(date(2026, 11, day)) for day in (9, 10, 11)])

    await sync.serve(key, profile, d(2026, 11, 1), thursday, loader, now=thursday)
    async with engine.session_scope() as s:
        series = await repository.get_series(s, key)
    assert series.covered_to == d(2026, 11, 11)
    later = thursday + timedelta(minutes=10)
    await sync.serve(key, profile, d(2026, 11, 1), later, loader, now=later)
    assert len(calls) == 2  # tail stays due


async def test_iv_points_without_values_not_stored_and_tenors_separate(db):
    sync = HistorySync()
    k30 = SeriesKey("iv", "AAPL", "lseg", "1d", False, 30, "")
    k60 = SeriesKey("iv", "AAPL", "lseg", "1d", False, 60, "")
    profile = Profile("iv", "1d")

    async def loader(start, end):
        return Loaded(items=[point(date(2026, 11, 9)), VolatilityPoint(date=date(2026, 11, 10))])

    await sync.serve(k30, profile, d(2026, 11, 1), SATURDAY, loader, now=SATURDAY)
    res = await sync.serve(k30, profile, d(2026, 11, 1), SATURDAY, loader, now=SATURDAY)
    assert [p.date for p in res.items] == [date(2026, 11, 9)]
    calls = []

    async def other(start, end):
        calls.append(1)
        return Loaded(items=[point(date(2026, 11, 9), "0.3")])

    res60 = await sync.serve(k60, profile, d(2026, 11, 1), SATURDAY, other, now=SATURDAY)
    assert calls == [1] and res60.items[0].iv == Decimal("0.3")


async def test_clear_and_status(db):
    sync, prov = HistorySync(), FakeProvider(date(2026, 10, 1), date(2026, 11, 13))
    await serve(sync, prov, d(2026, 10, 1), SATURDAY, SATURDAY)
    async with engine.session_scope() as s:
        status = await repository.status(s)
    assert status["prices"]["series"] == 1 and status["prices"]["rows"] > 20
    assert status["prices"]["intervals"]["1d"]["rows"] == status["prices"]["rows"]
    async with engine.session_scope() as s:
        none = await repository.clear(s, "prices", "AAPL", "schwab")
        assert none == {"series": 0, "rows": 0}
        gone = await repository.clear(s, "prices", "AAPL", None, "1d")
    assert gone["series"] == 1 and gone["rows"] > 20


async def test_migration_is_idempotent_and_guarded(db):
    await ensure_schema(db)
    await ensure_schema(db, migrate=False)
    await _drop_all(db)
    with pytest.raises(RuntimeError):
        await ensure_schema(db, migrate=False)
    await ensure_schema(db, migrate=True)
