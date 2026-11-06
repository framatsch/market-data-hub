"""Conservative US equity session clock (holidays deliberately count as weekdays)."""

import re
from datetime import UTC, datetime, time, timedelta
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
