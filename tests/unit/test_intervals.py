from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.models.price import PriceBar
from app.providers.ibkr import IBKRProvider
from app.providers.lseg import LSEGProvider
from app.providers.polygon import PolygonProvider
from app.providers.prixe import PrixeProvider
from app.providers.schwab import SchwabProvider
from app.utils.errors import ProviderError
from app.utils.intervals import (
    CANONICAL_INTERVALS,
    aggregate_bars,
    bucket_bounds,
    derived_intervals,
    normalize_interval,
    select_source_interval,
    widen_range,
)

POLYGON = PolygonProvider.native_intervals
SCHWAB = SchwabProvider.native_intervals
IBKR = IBKRProvider.native_intervals
LSEG = LSEGProvider.native_intervals
PRIXE = PrixeProvider.native_intervals


def utc(*args):
    return datetime(*args, tzinfo=UTC)


@pytest.mark.parametrize(
    "raw,expected",
    [("1D", "1d"), ("60m", "1h"), ("1wk", "1w"), ("1W", "1w"), (" 4H ", "4h"), ("3h", "3h")],
)
def test_normalize(raw, expected):
    assert normalize_interval(raw) == expected


@pytest.mark.parametrize(
    "native,target,source",
    [
        (POLYGON, "15m", "5m"),
        (POLYGON, "4h", "1h"),
        (POLYGON, "1w", "1d"),
        (POLYGON, "1h", None),
        (SCHWAB, "1h", "30m"),
        (SCHWAB, "4h", "30m"),
        (IBKR, "4h", "1h"),
        (LSEG, "15m", "5m"),
        (LSEG, "4h", "1h"),
        (PRIXE, "4h", "1h"),
        (POLYGON, "1d", None),
        (POLYGON, "30m", None),
        (POLYGON, "3h", None),
    ],
)
def test_source_selection(native, target, source):
    got = None if target in native else select_source_interval(target, native)
    assert got == source


def test_derived_lists():
    assert derived_intervals(POLYGON) == ["15m", "4h", "1w"]
    assert derived_intervals(SCHWAB) == ["1h", "4h"]
    assert derived_intervals(IBKR) == ["4h"]
    assert derived_intervals(LSEG) == ["15m", "4h"]


@pytest.mark.parametrize(
    "provider", [PolygonProvider, SchwabProvider, IBKRProvider, LSEGProvider, PrixeProvider]
)
def test_every_provider_declares_daily_and_all_canonical_resolve(provider):
    native = provider.native_intervals
    assert "1d" in native
    for interval in CANONICAL_INTERVALS:
        assert interval in native or select_source_interval(interval, native)


def test_lseg_no_longer_maps_substitutes():
    mapping_source = LSEGProvider._map_interval
    provider = LSEGProvider.__new__(LSEGProvider)
    for interval in ("2m", "15m"):
        with pytest.raises(ProviderError):
            mapping_source(provider, interval)


def test_weekly_bucket_by_utc_date():
    for start in (utc(2026, 11, 9, 2), utc(2026, 11, 9, 6)):
        low, high = widen_range("1w", start, start)
        assert low == utc(2026, 11, 9) and high == utc(2026, 11, 15, 23, 59, 59)


def test_weekly_widening_tuesday_to_thursday():
    low, high = widen_range("1w", utc(2026, 11, 3), utc(2026, 11, 5))
    assert (low, high) == (utc(2026, 11, 2), utc(2026, 11, 8, 23, 59, 59))


def test_intraday_buckets_clock_aligned_in_new_york():
    low, high = bucket_bounds("4h", utc(2026, 11, 11, 18, 0))  # 13:00 ET
    assert low == utc(2026, 11, 11, 17) and high == utc(2026, 11, 11, 20, 59, 59)
    low, _ = bucket_bounds("1h", utc(2026, 11, 11, 14, 45))
    assert low == utc(2026, 11, 11, 14)


def test_dst_change_bucket():
    # 2026-11-01: clocks go back; midnight-based buckets still contain the instant.
    instant = utc(2026, 11, 1, 12)
    low, high = bucket_bounds("4h", instant)
    assert low <= instant <= high


def bar(start, o, h, low, c, v=100):
    return PriceBar(
        symbol="AAPL", start=start, end=start, open=Decimal(o), high=Decimal(h),
        low=Decimal(low), close=Decimal(c), volume=v, provider="polygon",
        source_instrument="AAPL",
    )


def test_weekly_aggregation_values_and_daily_stamps():
    opens, highs, lows, closes = (10, 11, 12, 13, 14), (12, 15, 13, 14, 16), (9, 10, 11, 12, 13), (11, 12, 13, 14, 15)
    bars = [
        bar(utc(2026, 11, 9 + i, 5 if i % 2 else 0), opens[i], highs[i], lows[i], closes[i])
        for i in range(5)
    ]
    [week] = aggregate_bars(bars, "1w", "1d")
    assert (week.open, week.high, week.low, week.close, week.volume) == (10, 16, 9, 15, 500)
    assert week.start == bars[0].start and week.end == bars[-1].end
    assert week.source_interval == "1d" and week.source_instrument == "AAPL"


def test_holiday_week_starts_on_first_bar_and_empty_bucket_yields_nothing():
    bars = [bar(utc(2026, 11, 10 + i), 1, 2, 1, 2) for i in range(4)]
    [week] = aggregate_bars(bars, "1w", "1d")
    assert week.start == utc(2026, 11, 10)
    assert aggregate_bars([], "1w", "1d") == []


def test_four_hour_buckets_of_rth_hourly_bars():
    bars = [bar(utc(2026, 11, 11, h), 1, 2, 1, 2) for h in (14, 15, 16, 17, 18, 19, 20)]
    # 09:00..15:00 ET -> 08-12 holds 09,10,11 ; 12-16 holds 12,13,14,15
    out = aggregate_bars(bars, "4h", "1h")
    assert [b.volume for b in out] == [300, 400]
