from datetime import UTC, datetime, timedelta

from app.store.sync import Coverage, Profile, plan

DAILY = Profile("prices", "1d")
IV = Profile("iv", "1d")


def u(*a):
    return datetime(*a, tzinfo=UTC)


SAT = u(2026, 11, 14, 12)
WED = u(2026, 11, 11, 16)


def kinds(steps):
    return [s.kind for s in steps]


def test_unknown_series_does_full_load():
    steps = plan(DAILY, u(2026, 10, 1), SAT, Coverage(), SAT, 300)
    assert kinds(steps) == ["full_load"]


def test_unknown_series_always_asks_the_provider():
    cov = Coverage(sync_failed_at=SAT - timedelta(seconds=10))
    assert kinds(plan(DAILY, u(2026, 10, 1), SAT, cov, SAT, 300)) == ["full_load"]


def test_covered_and_settled_needs_no_call():
    cov = Coverage(u(2026, 10, 1), u(2026, 11, 13), SAT - timedelta(hours=1))
    assert plan(DAILY, u(2026, 10, 15), SAT, cov, SAT, 300) == []


def test_session_request_includes_forming_bar_and_is_throttled():
    cov = Coverage(u(2026, 10, 1), u(2026, 11, 10), WED - timedelta(seconds=60))
    assert plan(DAILY, u(2026, 10, 1), WED, cov, WED, 300) == []
    cov = Coverage(u(2026, 10, 1), u(2026, 11, 10), WED - timedelta(seconds=600))
    assert kinds(plan(DAILY, u(2026, 10, 1), WED, cov, WED, 300)) == ["tail_sync"]
    assert kinds(plan(DAILY, u(2026, 10, 1), WED, Coverage(u(2026, 10, 1), u(2026, 11, 10), WED), WED, 300, force=True)) == ["tail_sync"]


def test_earlier_start_backfills_then_tails():
    cov = Coverage(u(2026, 10, 1), u(2026, 11, 10), WED - timedelta(hours=1))
    steps = plan(DAILY, u(2026, 9, 1), WED, cov, WED, 300)
    assert kinds(steps) == ["backfill", "tail_sync"]
    assert steps[0].start == u(2026, 9, 1)


def test_weekly_start_moves_to_monday():
    weekly = Profile("prices", "1w")
    cov = Coverage(u(2026, 11, 2), u(2026, 11, 9), SAT - timedelta(hours=1))
    # start Wednesday Nov 4 is inside the covered week: nothing to backfill
    assert plan(weekly, u(2026, 11, 4), SAT, cov, SAT, 300) == []
    cov = Coverage(u(2026, 11, 4), u(2026, 11, 9), SAT - timedelta(hours=1))
    assert kinds(plan(weekly, u(2026, 11, 4), SAT, cov, SAT, 300)) == ["backfill"]


def test_iv_tail_stays_due_until_point_is_published():
    thursday = u(2026, 11, 12, 22)
    cov = Coverage(u(2026, 10, 1), u(2026, 11, 11), thursday - timedelta(minutes=10))
    assert kinds(plan(IV, u(2026, 10, 1), thursday, cov, thursday, 300)) == ["tail_sync"]
    saturday_cov = Coverage(u(2026, 10, 1), u(2026, 11, 13), SAT - timedelta(hours=1))
    assert plan(IV, u(2026, 10, 1), SAT, saturday_cov, SAT, 300) == []


def test_rth_hourly_series_settled_evening_needs_no_call():
    hourly = Profile("prices", "1h")
    evening = u(2026, 11, 12, 0)
    cov = Coverage(u(2026, 11, 11, 14), u(2026, 11, 11, 20), evening - timedelta(hours=1))
    assert plan(hourly, u(2026, 11, 11, 14), evening, cov, evening, 300) == []


def test_intraday_backfill_is_throttled():
    hourly = Profile("prices", "1h")
    evening = u(2026, 11, 12, 0)
    recent = Coverage(u(2026, 11, 11, 14), u(2026, 11, 11, 20), evening - timedelta(seconds=30))
    assert plan(hourly, u(2026, 11, 10), evening, recent, evening, 300) == []
    old = Coverage(u(2026, 11, 11, 14), u(2026, 11, 11, 20), evening - timedelta(hours=1))
    assert kinds(plan(hourly, u(2026, 11, 10), evening, old, evening, 300)) == ["backfill"]


def test_naive_bar_stamps_are_stored_as_utc_whatever_the_system_zone(monkeypatch) -> None:
    import time
    from decimal import Decimal

    from app.models.price import PriceBar
    from app.store.repository import _bar_values

    monkeypatch.setenv("TZ", "Europe/Berlin")
    time.tzset()
    try:
        bar = PriceBar(
            symbol="AAPL",
            start=datetime(2026, 10, 5),
            end=datetime(2026, 10, 5),
            open=Decimal(1),
            high=Decimal(1),
            low=Decimal(1),
            close=Decimal(1),
            volume=1,
            provider="ibkr",
        )
        values = _bar_values(1, bar)
    finally:
        monkeypatch.undo()
        time.tzset()
    assert values["bar_start"] == datetime(2026, 10, 5, tzinfo=UTC)
    assert values["bar_end"] == datetime(2026, 10, 5, tzinfo=UTC)
    assert values["bar_date"].isoformat() == "2026-10-05"
