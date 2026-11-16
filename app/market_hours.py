"""Conservative US equity session clock (holidays deliberately count as weekdays)."""

import re
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
MarketState = Literal["session", "settle_grace", "settled"]


def as_utc(now: datetime) -> datetime:
    return now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)


def interval_parts(interval: str) -> tuple[int, str]:
    match = re.fullmatch(r"([1-9]\d*)(s|m|min|h|d|w|wk|mo)", interval)
    if match is None:
        raise ValueError(f"Unsupported interval: {interval}")
    count, unit = match.groups()
    return int(count), {"min": "m", "wk": "w"}.get(unit, unit)


def bar_length_seconds(interval: str) -> int | None:
    count, unit = interval_parts(interval)
    seconds = {"s": 1, "m": 60, "h": 3600}.get(unit)
    return count * seconds if seconds else None


def market_state(now: datetime, extended: bool = False) -> MarketState:
    local = as_utc(now).astimezone(ET)
    if local.weekday() >= 5:
        return "settled"
    opened = datetime.combine(local.date(), time(4) if extended else time(9, 30), ET)
    closed = datetime.combine(local.date(), time(20) if extended else time(16), ET)
    if opened <= local < closed:
        return "session"
    if closed <= local < closed + timedelta(minutes=30):
        return "settle_grace"
    return "settled"


def next_open(now: datetime, extended: bool = False) -> datetime:
    local = as_utc(now).astimezone(ET)
    candidate = datetime.combine(local.date(), time(4) if extended else time(9, 30), ET)
    if candidate <= local:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def next_transition(now: datetime) -> datetime:
    """Return the next weekday premarket/open/close/after-hours boundary in ET."""
    local = as_utc(now).astimezone(ET)
    day = local.date()
    while True:
        if day.weekday() < 5:
            for boundary in (time(4), time(9, 30), time(16), time(20)):
                candidate = datetime.combine(day, boundary, ET)
                if candidate > local:
                    return candidate
        day += timedelta(days=1)


def current_period_start(interval: str, now: datetime) -> datetime:
    count, unit = interval_parts(interval)
    local = as_utc(now).astimezone(ET)
    midnight = datetime.combine(local.date(), time(), ET)
    length = bar_length_seconds(interval)
    if length is not None:
        elapsed = int((as_utc(local) - as_utc(midnight)).total_seconds())
        return (
            as_utc(midnight) + timedelta(seconds=elapsed // length * length)
        ).astimezone(ET)
    if unit == "d":
        return midnight
    if unit == "w":
        return midnight - timedelta(days=local.weekday())
    month = (local.month - 1) // count * count + 1
    return midnight.replace(month=month, day=1)


STORABLE_INTERVALS = ("1h", "4h", "1d", "1w")
_SETTLE_GRACE = timedelta(minutes=30)


def trading_date(bar_start: datetime) -> date:
    """Trading date of a daily bar: the UTC calendar date of its start.

    Polygon stamps daily bars at New York midnight (04:00/05:00 UTC), the other
    providers at UTC midnight; the UTC date is the trading date in both cases.
    """
    return as_utc(bar_start).date()


def _is_weekday_closed_today(now: datetime) -> bool:
    local = as_utc(now).astimezone(ET)
    if local.weekday() >= 5:
        return False
    close = datetime.combine(local.date(), time(16), ET)
    return local >= close + _SETTLE_GRACE


def last_closed_day(now: datetime) -> date:
    """Newest weekday whose session is over (close plus grace); holidays count as weekdays."""
    local = as_utc(now).astimezone(ET)
    day = local.date()
    if not _is_weekday_closed_today(now):
        day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def is_closed(day: date, now: datetime) -> bool:
    return day <= last_closed_day(now)


def week_monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _period_length(interval: str) -> timedelta:
    length = bar_length_seconds(interval)
    if length is None:
        raise ValueError(f"Not an intraday interval: {interval}")
    return timedelta(seconds=length)


def _period_end(interval: str, bar_start: datetime) -> datetime:
    start = current_period_start(interval, as_utc(bar_start))
    return as_utc(start) + _period_length(interval)


def is_bar_closed(
    interval: str, bar_start: datetime, now: datetime, extended_hours: bool = False
) -> bool:
    """Whether the bar that starts at `bar_start` is final (see design D3)."""
    now = as_utc(now)
    if interval == "1d":
        return is_closed(trading_date(bar_start), now)
    if interval == "1w":
        monday = week_monday(trading_date(bar_start))
        return is_closed(monday + timedelta(days=4), now)
    if _period_end(interval, bar_start) <= now:
        return True
    return not extended_hours and market_state(now) == "settled"


def newest_closed_key(
    interval: str, now: datetime, extended_hours: bool = False
) -> datetime:
    """Start of the newest closed bar period (midnight UTC of the date for 1d/1w)."""
    now = as_utc(now)
    if interval == "1d":
        day = last_closed_day(now)
        return datetime.combine(day, time(), UTC)
    if interval == "1w":
        day = last_closed_day(now)
        monday = week_monday(day)
        if day.weekday() < 4:  # Friday of that week is not closed yet
            monday -= timedelta(days=7)
        return datetime.combine(monday, time(), UTC)
    length = _period_length(interval)
    if not extended_hours and market_state(now) == "settled":
        day = last_closed_day(now)
        close = datetime.combine(day, time(16), ET)
        return as_utc(current_period_start(interval, close - timedelta(seconds=1)))
    return as_utc(current_period_start(interval, now)) - length
