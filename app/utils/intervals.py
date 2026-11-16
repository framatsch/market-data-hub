# market-data-hub - FastAPI data service for market and company data
# Copyright (C) 2026  Market Data Hub Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Canonical bar intervals, source selection and aggregation (derived-price-intervals)."""

from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime, time, timedelta

from app.market_hours import (
    as_utc,
    bar_length_seconds,
    current_period_start,
    interval_parts,
    trading_date,
    week_monday,
)
from app.models.price import PriceBar

CANONICAL_INTERVALS = ("1m", "5m", "15m", "1h", "4h", "1d", "1w")
ALIASES = {"60m": "1h", "1wk": "1w"}


def normalize_interval(raw: str) -> str:
    """Lower-case the interval and map the aliases `60m` and `1wk`."""
    value = (raw or "").strip().lower()
    return ALIASES.get(value, value)


def _seconds(interval: str) -> int | None:
    try:
        return bar_length_seconds(interval)
    except ValueError:
        return None


def select_source_interval(target: str, native: Iterable[str]) -> str | None:
    """Source interval for a derived canonical `target`; None when not derivable."""
    native = set(native)
    if target == "1w":
        return "1d" if "1d" in native else None
    if target not in CANONICAL_INTERVALS or target in {"1d"}:
        return None
    length = _seconds(target)
    if length is None:
        return None
    best: tuple[int, str] | None = None
    for candidate in native:
        size = _seconds(candidate)
        if size is None or size >= length or length % size != 0:
            continue
        if best is None or size > best[0]:
            best = (size, candidate)
    return best[1] if best else None


def derived_intervals(native: Iterable[str]) -> list[str]:
    """Canonical intervals the provider answers by derivation."""
    native = set(native)
    return [
        interval
        for interval in CANONICAL_INTERVALS
        if interval not in native and select_source_interval(interval, native)
    ]


def bucket_bounds(interval: str, instant: datetime) -> tuple[datetime, datetime]:
    """Inclusive start and end of the bucket of `interval` that contains `instant`.

    Weeks are ISO weeks by UTC calendar date (Monday 00:00:00 to Sunday 23:59:59 UTC);
    intraday buckets are clock-aligned in America/New_York.
    """
    instant = as_utc(instant)
    if interval == "1w":
        monday = week_monday(instant.date())
        start = datetime.combine(monday, time(), UTC)
        return start, start + timedelta(days=7) - timedelta(seconds=1)
    length = _seconds(interval)
    if length is None:
        raise ValueError(f"Not a derivable interval: {interval}")
    start = as_utc(current_period_start(interval, instant))
    return start, start + timedelta(seconds=length) - timedelta(seconds=1)


def widen_range(
    interval: str, start: datetime, end: datetime
) -> tuple[datetime, datetime]:
    """Move `start` to the start and `end` to the end of their buckets."""
    return bucket_bounds(interval, start)[0], bucket_bounds(interval, end)[1]


def _bucket_key(target: str, bar: PriceBar) -> datetime:
    if target == "1w":
        return datetime.combine(week_monday(trading_date(bar.start)), time(), UTC)
    return as_utc(current_period_start(target, bar.start))


def aggregate_bars(bars: list[PriceBar], target: str, source: str) -> list[PriceBar]:
    """Aggregate source bars into one bar per bucket (empty buckets yield no bar)."""
    groups: dict[datetime, list[PriceBar]] = defaultdict(list)
    for bar in sorted(bars, key=lambda b: b.start):
        groups[_bucket_key(target, bar)].append(bar)
    result = []
    for key in sorted(groups):
        group = groups[key]
        first, last = group[0], group[-1]
        result.append(
            first.model_copy(
                update={
                    "end": last.end,
                    "open": first.open,
                    "high": max(b.high for b in group),
                    "low": min(b.low for b in group),
                    "close": last.close,
                    "volume": sum(b.volume for b in group),
                    "source_interval": source,
                }
            )
        )
    return result


def is_canonical(interval: str) -> bool:
    try:
        interval_parts(interval)
    except ValueError:
        return False
    return interval in CANONICAL_INTERVALS
