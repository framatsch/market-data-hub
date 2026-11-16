from datetime import datetime

import pytest

from app.market_hours import (
    ET,
    bar_length_seconds,
    current_period_start,
    market_state,
    next_open,
    next_transition,
)


@pytest.mark.parametrize(
    "clock,state",
    [
        ("2026-11-04T09:29:59", "settled"),
        ("2026-11-04T09:30:00", "session"),
        ("2026-11-04T15:59:59", "session"),
        ("2026-11-04T16:00:00", "settle_grace"),
        ("2026-11-04T16:29:59", "settle_grace"),
        ("2026-11-04T16:30:00", "settled"),
        ("2026-11-07T11:00:00", "settled"),
    ],
)
def test_market_states(clock, state):
    assert market_state(datetime.fromisoformat(clock).replace(tzinfo=ET)) == state


@pytest.mark.parametrize(
    "clock,next_clock,extended",
    [
        ("2026-11-04T08:00:00", "2026-11-04T09:30:00", False),
        ("2026-11-04T18:00:00", "2026-11-05T09:30:00", False),
        ("2026-11-06T17:00:00", "2026-11-09T09:30:00", False),
        ("2026-11-07T10:00:00", "2026-11-09T09:30:00", False),
        ("2026-11-04T03:00:00", "2026-11-04T04:00:00", True),
        ("2026-10-30T17:00:00", "2026-11-02T09:30:00", False),
    ],
)
def test_next_open(clock, next_clock, extended):
    assert next_open(
        datetime.fromisoformat(clock).replace(tzinfo=ET), extended
    ) == datetime.fromisoformat(next_clock).replace(tzinfo=ET)


def test_extended_session_and_grace():
    assert market_state(datetime(2026, 11, 4, 18, tzinfo=ET), True) == "session"
    assert (
        market_state(datetime(2026, 11, 4, 20, 10, tzinfo=ET), True) == "settle_grace"
    )
    assert market_state(datetime(2026, 11, 4, 20, 30, tzinfo=ET), True) == "settled"


@pytest.mark.parametrize(
    "interval,start,length",
    [
        ("1m", "2026-11-04T11:17:00", 60),
        ("5min", "2026-11-04T11:15:00", 300),
        ("1h", "2026-11-04T11:00:00", 3600),
        ("1d", "2026-11-04T00:00:00", None),
        ("1w", "2026-11-02T00:00:00", None),
        ("1wk", "2026-11-02T00:00:00", None),
        ("1mo", "2026-11-01T00:00:00", None),
    ],
)
def test_periods(interval, start, length):
    now = datetime(2026, 11, 4, 11, 17, 42, tzinfo=ET)
    assert current_period_start(interval, now) == datetime.fromisoformat(start).replace(
        tzinfo=ET
    )
    assert bar_length_seconds(interval) == length


@pytest.mark.parametrize("interval", ["0m", "month", "-1h", "1M"])
def test_invalid_intervals(interval):
    with pytest.raises(ValueError):
        bar_length_seconds(interval)


@pytest.mark.parametrize(
    "clock,expected",
    [
        ("2026-11-04T03:59:59-05:00", "2026-11-04T04:00:00-05:00"),
        ("2026-11-04T04:00:00-05:00", "2026-11-04T09:30:00-05:00"),
        ("2026-11-04T09:30:00-05:00", "2026-11-04T16:00:00-05:00"),
        ("2026-11-04T16:00:00-05:00", "2026-11-04T20:00:00-05:00"),
        ("2026-11-06T20:00:00-05:00", "2026-11-09T04:00:00-05:00"),
        ("2026-11-07T10:00:00-05:00", "2026-11-09T04:00:00-05:00"),
        ("2026-10-30T20:00:00-04:00", "2026-11-02T04:00:00-05:00"),
        ("2026-03-06T20:00:00-05:00", "2026-03-09T04:00:00-04:00"),
        ("2026-11-04T08:00:00", "2026-11-04T04:00:00-05:00"),
    ],
)
def test_next_transition(clock, expected):
    from app.market_hours import as_utc

    actual = next_transition(datetime.fromisoformat(clock))
    assert as_utc(actual) == as_utc(datetime.fromisoformat(expected))
    assert actual.tzinfo == ET


# ---- history store closed-bar rules -------------------------------------------
from datetime import UTC as _UTC
from datetime import date as _date
from datetime import datetime as _dt

from app.market_hours import (
    is_bar_closed,
    last_closed_day,
    newest_closed_key,
    trading_date,
)


def _u(*a):
    return _dt(*a, tzinfo=_UTC)


def test_last_closed_day_session_grace_evening_weekend():
    assert last_closed_day(_u(2026, 11, 11, 16, 0)) == _date(2026, 11, 10)  # Wed 11:00 ET
    assert last_closed_day(_u(2026, 11, 11, 21, 10)) == _date(2026, 11, 10)  # 16:10, grace
    assert last_closed_day(_u(2026, 11, 11, 21, 45)) == _date(2026, 11, 11)  # 16:45
    assert last_closed_day(_u(2026, 11, 14, 12, 0)) == _date(2026, 11, 13)  # Saturday
    assert last_closed_day(_u(2026, 11, 16, 13, 0)) == _date(2026, 11, 13)  # Monday morning


def test_trading_date_is_utc_date_for_both_stamps():
    assert trading_date(_u(2026, 11, 10, 0)) == _date(2026, 11, 10)
    assert trading_date(_u(2026, 11, 10, 5)) == _date(2026, 11, 10)  # NY midnight


def test_bar_closed_rules():
    wed_session = _u(2026, 11, 11, 16, 0)
    assert not is_bar_closed("1d", _u(2026, 11, 11), wed_session)
    assert is_bar_closed("1d", _u(2026, 11, 10), wed_session)
    assert not is_bar_closed("1w", _u(2026, 11, 9), wed_session)
    assert is_bar_closed("1w", _u(2026, 11, 2), wed_session)
    assert is_bar_closed("1w", _u(2026, 11, 9), _u(2026, 11, 13, 21, 45))
    now = _u(2026, 11, 11, 16, 20)  # 11:20 ET
    assert not is_bar_closed("1h", _u(2026, 11, 11, 16), now)
    assert is_bar_closed("1h", _u(2026, 11, 11, 15), now)
    evening = _u(2026, 11, 12, 0, 0)
    assert is_bar_closed("1h", _u(2026, 11, 11, 20), evening)  # RTH, settled
    assert not is_bar_closed(
        "1h", _u(2026, 11, 11, 23), _u(2026, 11, 11, 23, 30), extended_hours=True
    )


def test_newest_closed_key():
    assert newest_closed_key("1d", _u(2026, 11, 14, 12)) == _u(2026, 11, 13)
    assert newest_closed_key("1w", _u(2026, 11, 11, 16)) == _u(2026, 11, 2)
    assert newest_closed_key("1w", _u(2026, 11, 14, 12)) == _u(2026, 11, 9)
    assert newest_closed_key("1h", _u(2026, 11, 12, 0)) == _u(2026, 11, 11, 20)
    assert newest_closed_key("4h", _u(2026, 11, 12, 0)) == _u(2026, 11, 11, 17)
