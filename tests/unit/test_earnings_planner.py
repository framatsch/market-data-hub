from datetime import UTC, date, datetime, timedelta

import pytest

from app.services.earnings_planner import HistoryInput, SyncInfo, plan_refresh

NOW = datetime(2026, 11, 17, 15, tzinfo=UTC)
TODAY = date(2026, 11, 17)
RESYNC, RETRY = timedelta(hours=24), timedelta(minutes=30)


def plan(**kwargs):
    values = {
        "now": NOW, "today": TODAY, "request_end": TODAY + timedelta(days=90),
        "needs_calendar": True, "needs_history": False, "calendar": None,
        "symbols": [], "budget_remaining": None,
        "calendar_resync": RESYNC, "retry": RETRY,
    }
    return plan_refresh(**(values | kwargs))


def fresh(hours=3, covered=365):
    return SyncInfo(NOW - timedelta(hours=hours), None, TODAY + timedelta(days=covered))


@pytest.mark.parametrize("calendar,due", [
    (None, True),
    (SyncInfo(), True),
    (fresh(3), False),
    (fresh(24), True),
    (fresh(3, covered=30), True),
    (SyncInfo(NOW - timedelta(hours=30), NOW - timedelta(minutes=10), TODAY), False),
    (SyncInfo(NOW - timedelta(hours=30), NOW - timedelta(minutes=31), TODAY), True),
    (SyncInfo(None, NOW - timedelta(minutes=10), None), False),
])
def test_calendar_due(calendar, due):
    assert plan(calendar=calendar).calendar_due is due


def test_range_beyond_horizon_is_capped_and_not_refetched_forever():
    assert plan(calendar=fresh(1, 365), request_end=TODAY + timedelta(days=800)).calendar_due is False


def test_past_only_request_never_needs_calendar():
    assert plan(needs_calendar=False, calendar=None).calendar_due is False


@pytest.mark.parametrize("sync,recent,due", [
    (None, False, True),
    (SyncInfo(), False, True),
    (SyncInfo(NOW - timedelta(days=90)), False, False),
    (SyncInfo(NOW - timedelta(hours=13)), True, True),
    (SyncInfo(NOW - timedelta(hours=11)), True, False),
    (SyncInfo(NOW - timedelta(hours=13), NOW - timedelta(minutes=5)), True, False),
    (SyncInfo(None, NOW - timedelta(minutes=40)), False, True),
])
def test_history_due(sync, recent, due):
    result = plan(needs_history=True, symbols=[HistoryInput("AAPL", sync, recent)])
    assert (result.history_due == ("AAPL",)) is due


def test_next_never_requests_history():
    assert plan(needs_history=False, symbols=[HistoryInput("AAPL", None)]).history_due == ()


def test_retry_pause_is_reported_separately_from_budget_pending():
    paused = SyncInfo(None, NOW - timedelta(minutes=1))
    result = plan(needs_history=True, budget_remaining=1, calendar=fresh(),
                  symbols=[HistoryInput("A", paused), HistoryInput("B", None), HistoryInput("C", None)])
    assert (result.history_paused, result.history_due, result.history_pending) == (("A",), ("B",), ("C",))


@pytest.mark.parametrize("remaining,calendar_due_,expected_due", [
    (None, True, 5), (20, False, 5), (3, False, 3), (3, True, 2), (1, True, 0), (0, True, 0), (0, False, 0),
])
def test_budget_limits_history_in_request_order_after_calendar(remaining, calendar_due_, expected_due):
    names = [f"S{i}" for i in range(5)]
    result = plan(needs_history=True, budget_remaining=remaining,
                  calendar=None if calendar_due_ else fresh(),
                  symbols=[HistoryInput(name, None) for name in names])
    assert result.calendar_due is calendar_due_
    assert result.history_due == tuple(names[:expected_due])
    assert result.history_pending == tuple(names[expected_due:])
