from datetime import UTC, date, datetime, timedelta

from app.services.earnings_planner import (
    SymbolInput,
    SyncInfo,
    plan_days,
    plan_symbols,
    window_days,
)

RETRY = timedelta(minutes=30)
RESYNC = timedelta(days=7)
WED = date(2026, 11, 18)
NOW = datetime(2026, 11, 18, 15, tzinfo=UTC)


def synced(at):
    return SyncInfo(synced_at=at)


def test_window_skips_weekends():
    days = window_days(WED, 7)
    assert days[0] == date(2026, 11, 17) and days[1] == WED
    assert days[2:] == [date(2026, 11, d) for d in (19, 20, 23, 24, 25, 26, 27)]
    assert all(d.weekday() < 5 for d in days)
    # Over a weekend: previous weekday is Friday, Saturday itself is not requested.
    sat = date(2026, 11, 21)
    assert window_days(sat, 2) == [date(2026, 11, 20), date(2026, 11, 23), date(2026, 11, 24)]


def plan(syncs, budget=None, now=NOW):
    return plan_days(now=now, today=WED, weekdays=7, syncs=syncs, retry=RETRY, budget_remaining=budget)


def test_first_use_requests_whole_window_in_date_order():
    result = plan({})
    assert list(result.due) == window_days(WED, 7) and not result.pending


def test_steady_state_refreshes_five_days():
    yesterday = NOW - timedelta(hours=24)
    syncs = {d: synced(yesterday) for d in window_days(date(2026, 11, 17), 7)}
    result = plan(syncs)
    # previous weekday, today, next two weekdays and the new last day of the window
    assert list(result.due) == [date(2026, 11, 17), WED, date(2026, 11, 19), date(2026, 11, 20), date(2026, 11, 27)]


def test_fresh_days_are_not_refetched_and_failures_pause():
    syncs = {d: synced(NOW - timedelta(hours=2)) for d in window_days(WED, 7)}
    assert plan(syncs).due == ()
    syncs[WED] = SyncInfo(synced_at=NOW - timedelta(hours=30), failed_at=NOW - timedelta(minutes=5))
    result = plan(syncs)
    assert result.due == () and result.paused == (WED,)
    syncs[WED] = SyncInfo(synced_at=NOW - timedelta(hours=30), failed_at=NOW - timedelta(minutes=45))
    assert plan(syncs).due == (WED,)


def test_budget_cuts_in_date_order():
    result = plan({}, budget=3)
    assert list(result.due) == window_days(WED, 7)[:3] and len(result.pending) == 6


def sym(symbol, sync=None, **kwargs):
    return SymbolInput(symbol, sync, **kwargs)


def sym_plan(items, **kwargs):
    base = {
        "now": NOW, "needs_past": False, "needs_next": True, "has_day_calendar": True,
        "resync": RESYNC, "retry": RETRY, "budget_remaining": None,
    }
    return plan_symbols(symbols=items, **{**base, **kwargs})


def test_never_synced_rules():
    assert sym_plan([sym("ADI")]).due == ("ADI",)  # window lacks it
    assert sym_plan([sym("ADI", in_window=True, has_upcoming=True)]).due == ()  # window answers
    assert sym_plan([sym("ADI", in_window=True)], needs_past=True).due == ("ADI",)
    assert sym_plan([sym("ADI")], needs_next=False, needs_past=False).due == ()


def test_known_next_date_is_not_refetched_for_age():
    old = synced(NOW - timedelta(days=60))
    assert sym_plan([sym("ADI", old, has_upcoming=True, latest_event=date(2027, 2, 18))]).due == ()
    assert sym_plan([sym("ADI", old, has_upcoming=True, in_window=True)]).due == ()


def test_next_quarter_after_report_once():
    item = sym("ADI", synced(datetime(2026, 11, 10, tzinfo=UTC)), latest_event=date(2026, 11, 17))
    assert sym_plan([item]).due == ("ADI",)
    after = sym("ADI", synced(NOW - timedelta(hours=1)), latest_event=date(2026, 11, 17))
    assert sym_plan([after]).due == ()


def test_date_not_announced_weekly():
    latest = date(2026, 8, 19)
    assert sym_plan([sym("ADI", synced(NOW - timedelta(days=8)), latest_event=latest)]).due == ("ADI",)
    assert sym_plan([sym("ADI", synced(NOW - timedelta(days=3)), latest_event=latest)]).due == ()


def test_invalidation_and_actuals_without_day_calendar():
    invalid = SyncInfo(synced_at=NOW - timedelta(days=1), invalidated_at=NOW)
    assert sym_plan([sym("ADI", invalid, has_upcoming=True)]).due == ("ADI",)
    waiting = sym("ADI", synced(NOW - timedelta(hours=13)), has_upcoming=True, unreported_recent=True)
    assert sym_plan([waiting], has_day_calendar=False).due == ("ADI",)
    assert sym_plan([waiting], has_day_calendar=True).due == ()


def test_retry_pause_and_budget_order():
    failed = SyncInfo(failed_at=NOW - timedelta(minutes=5))
    result = sym_plan([sym("A", failed), sym("B"), sym("C"), sym("D")], budget_remaining=2)
    assert result.paused == ("A",) and result.due == ("B", "C") and result.pending == ("D",)


def test_reported_only_requests_refresh_after_the_report():
    # kind=reported or the history role: the request does not need the next event,
    # yet a stored report that happened since the last synchronisation is refreshed.
    item = sym("ADI", synced(datetime(2026, 11, 10, tzinfo=UTC)), latest_event=date(2026, 11, 17))
    assert sym_plan([item], needs_next=False, needs_past=True).due == ("ADI",)
    known = sym("ADI", synced(NOW - timedelta(days=60)), has_upcoming=True, latest_event=date(2027, 2, 18))
    assert sym_plan([known], needs_next=False, needs_past=True).due == ()
    invalid = SyncInfo(synced_at=NOW - timedelta(days=1), invalidated_at=NOW)
    assert sym_plan([sym("ADI", invalid, has_upcoming=True)], needs_next=False, needs_past=True).due == ("ADI",)


def test_actuals_rule_applies_when_the_window_is_not_used():
    # The service passes has_day_calendar=False when the request does not consult the window.
    waiting = sym("ADI", synced(NOW - timedelta(hours=13)), has_upcoming=True, unreported_recent=True)
    assert sym_plan([waiting], needs_next=False, needs_past=True, has_day_calendar=False).due == ("ADI",)
