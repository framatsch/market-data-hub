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
