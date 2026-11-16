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

"""Database access of the history store: series, price bars and IV points."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.market_hours import as_utc, trading_date, week_monday
from app.models.price import PriceBar
from app.models.volatility import VolatilityPoint
from app.store.models import HistorySeries, IvPointRow, PriceBarRow


@dataclass(frozen=True)
class SeriesKey:
    dataset: str  # prices | iv
    symbol: str
    provider: str
    interval: str
    extended_hours: bool = False
    tenor_days: int = 0
    instrument: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "symbol": self.symbol,
            "provider": self.provider,
            "interval": self.interval,
            "extended_hours": self.extended_hours,
            "tenor_days": self.tenor_days,
            "instrument": self.instrument,
        }


@dataclass
class Series:
    id: int
    key: SeriesKey
    sec_type: str | None
    source_instrument: str | None
    source_interval: str | None
    covered_from: datetime | None
    covered_to: datetime | None
    synced_at: datetime | None
    sync_failed_at: datetime | None

    @property
    def last_attempt(self) -> datetime | None:
        times = [t for t in (self.synced_at, self.sync_failed_at) if t is not None]
        return max(times) if times else None


def midnight(day: date) -> datetime:
    return datetime.combine(day, time(), UTC)


def _series(row: HistorySeries) -> Series:
    return Series(
        id=row.id,
        key=SeriesKey(
            dataset=row.dataset,
            symbol=row.symbol,
            provider=row.provider,
            interval=row.interval,
            extended_hours=row.extended_hours,
            tenor_days=row.tenor_days,
            instrument=row.instrument,
        ),
        sec_type=row.sec_type,
        source_instrument=row.source_instrument,
        source_interval=row.source_interval,
        covered_from=row.covered_from,
        covered_to=row.covered_to,
        synced_at=row.synced_at,
        sync_failed_at=row.sync_failed_at,
    )


async def get_series(session: AsyncSession, key: SeriesKey) -> Series | None:
    row = (
        await session.execute(select(HistorySeries).filter_by(**key.as_dict()))
    ).scalar_one_or_none()
    return _series(row) if row else None


async def get_or_create_series(
    session: AsyncSession,
    key: SeriesKey,
    sec_type: str | None = None,
    source_interval: str | None = None,
) -> Series:
    await session.execute(
        insert(HistorySeries)
        .values(**key.as_dict(), sec_type=sec_type, source_interval=source_interval)
        .on_conflict_do_nothing(constraint="uq_history_series_identity")
    )
    series = await get_series(session, key)
    assert series is not None
    return series


async def update_series(session: AsyncSession, series_id: int, **fields: Any) -> None:
    await session.execute(
        update(HistorySeries).where(HistorySeries.id == series_id).values(**fields)
    )


async def lock_series(session: AsyncSession, series_id: int) -> None:
    """Transaction-scoped advisory lock so replicas cannot interleave a replace."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:ns, :id)"), {"ns": 7204, "id": series_id}
    )


# ---------------------------------------------------------------- price bars


def bar_position(interval: str, bar: PriceBar) -> datetime:
    """Coverage position of a bar: instant for 1h/4h, midnight of its trading date."""
    if interval in {"1d", "1w"}:
        return midnight(trading_date(bar.start))
    return as_utc(bar.start)


def _row_to_bar(row: PriceBarRow, series: Series, symbol: str) -> PriceBar:
    return PriceBar(
        symbol=symbol,
        start=row.bar_start,
        end=row.bar_end,
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        volume=int(row.volume),
        provider=series.key.provider,
        source_instrument=series.source_instrument,
        source_interval=series.source_interval,
    )


def _bar_values(series_id: int, bar: PriceBar) -> dict[str, Any]:
    return {
        "series_id": series_id,
        "bar_start": as_utc(bar.start),
        "bar_date": trading_date(bar.start),
        "bar_end": as_utc(bar.end),
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
    }


async def read_bars(
    session: AsyncSession,
    series: Series,
    start: datetime,
    end: datetime,
) -> list[PriceBar]:
    interval = series.key.interval
    query = select(PriceBarRow).where(PriceBarRow.series_id == series.id)
    if interval == "1d":
        query = query.where(
            PriceBarRow.bar_date >= as_utc(start).date(),
            PriceBarRow.bar_date <= as_utc(end).date(),
        )
    elif interval == "1w":
        query = query.where(
            PriceBarRow.bar_date >= week_monday(as_utc(start).date()),
            PriceBarRow.bar_date <= as_utc(end).date(),
        )
    else:
        query = query.where(
            PriceBarRow.bar_start >= start, PriceBarRow.bar_start <= end
        )
    rows = (await session.execute(query.order_by(PriceBarRow.bar_start))).scalars()
    return [_row_to_bar(row, series, series.key.symbol) for row in rows]


async def newest_bars(
    session: AsyncSession, series: Series, count: int
) -> list[PriceBar]:
    rows = (
        await session.execute(
            select(PriceBarRow)
            .where(PriceBarRow.series_id == series.id)
            .order_by(PriceBarRow.bar_start.desc())
            .limit(count)
        )
    ).scalars()
    return sorted(
        (_row_to_bar(row, series, series.key.symbol) for row in rows),
        key=lambda bar: bar.start,
    )


async def upsert_bars(
    session: AsyncSession, series_id: int, bars: list[PriceBar]
) -> None:
    if not bars:
        return
    statement = insert(PriceBarRow).values([_bar_values(series_id, b) for b in bars])
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["series_id", "bar_start"],
            set_={
                name: statement.excluded[name]
                for name in (
                    "bar_date",
                    "bar_end",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                )
            },
        )
    )


async def replace_bars(
    session: AsyncSession, series_id: int, bars: list[PriceBar]
) -> None:
    await lock_series(session, series_id)
    await session.execute(delete(PriceBarRow).where(PriceBarRow.series_id == series_id))
    await upsert_bars(session, series_id, bars)


# ---------------------------------------------------------------- IV points


def iv_position(point: VolatilityPoint) -> datetime:
    return midnight(point.date)


def has_iv_value(point: VolatilityPoint) -> bool:
    return any(v is not None for v in (point.iv_call, point.iv_put, point.iv))


def _row_to_point(row: IvPointRow) -> VolatilityPoint:
    return VolatilityPoint(
        date=row.point_date, iv_call=row.iv_call, iv_put=row.iv_put, iv=row.iv
    )


async def read_points(
    session: AsyncSession, series: Series, start: datetime, end: datetime
) -> list[VolatilityPoint]:
    rows = (
        await session.execute(
            select(IvPointRow)
            .where(
                IvPointRow.series_id == series.id,
                IvPointRow.point_date >= as_utc(start).date(),
                IvPointRow.point_date <= as_utc(end).date(),
            )
            .order_by(IvPointRow.point_date)
        )
    ).scalars()
    return [_row_to_point(row) for row in rows]


async def newest_points(
    session: AsyncSession, series: Series, count: int
) -> list[VolatilityPoint]:
    rows = (
        await session.execute(
            select(IvPointRow)
            .where(IvPointRow.series_id == series.id)
            .order_by(IvPointRow.point_date.desc())
            .limit(count)
        )
    ).scalars()
    return sorted((_row_to_point(r) for r in rows), key=lambda p: p.date)


def _point_values(series_id: int, point: VolatilityPoint) -> dict[str, Any]:
    return {
        "series_id": series_id,
        "point_date": point.date,
        "iv_call": point.iv_call,
        "iv_put": point.iv_put,
        "iv": point.iv,
    }


async def upsert_points(
    session: AsyncSession, series_id: int, points: list[VolatilityPoint]
) -> None:
    points = [p for p in points if has_iv_value(p)]
    if not points:
        return
    statement = insert(IvPointRow).values([_point_values(series_id, p) for p in points])
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["series_id", "point_date"],
            set_={
                name: statement.excluded[name] for name in ("iv_call", "iv_put", "iv")
            },
        )
    )


async def replace_points(
    session: AsyncSession, series_id: int, points: list[VolatilityPoint]
) -> None:
    await lock_series(session, series_id)
    await session.execute(delete(IvPointRow).where(IvPointRow.series_id == series_id))
    await upsert_points(session, series_id, points)


# ---------------------------------------------------------------- admin


async def status(session: AsyncSession) -> dict[str, Any]:
    result: dict[str, Any] = {}
    bars = (
        await session.execute(
            select(
                HistorySeries.interval,
                func.count(func.distinct(HistorySeries.id)),
                func.count(PriceBarRow.series_id),
                func.min(PriceBarRow.bar_date),
                func.max(PriceBarRow.bar_date),
                func.max(HistorySeries.synced_at),
            )
            .select_from(HistorySeries)
            .outerjoin(PriceBarRow, PriceBarRow.series_id == HistorySeries.id)
            .where(HistorySeries.dataset == "prices")
            .group_by(HistorySeries.interval)
        )
    ).all()
    per_interval = {
        row[0]: {
            "series": row[1],
            "rows": row[2],
            "oldest": row[3].isoformat() if row[3] else None,
            "newest": row[4].isoformat() if row[4] else None,
            "newest_synced_at": row[5].isoformat() if row[5] else None,
        }
        for row in bars
    }
    newest_prices = [
        v["newest_synced_at"] for v in per_interval.values() if v["newest_synced_at"]
    ]
    oldest_prices = [v["oldest"] for v in per_interval.values() if v["oldest"]]
    newest_price_dates = [v["newest"] for v in per_interval.values() if v["newest"]]
    result["prices"] = {
        "series": sum(v["series"] for v in per_interval.values()),
        "rows": sum(v["rows"] for v in per_interval.values()),
        "oldest": min(oldest_prices) if oldest_prices else None,
        "newest": max(newest_price_dates) if newest_price_dates else None,
        "newest_synced_at": max(newest_prices) if newest_prices else None,
        "intervals": per_interval,
    }
    iv = (
        await session.execute(
            select(
                func.count(func.distinct(HistorySeries.id)),
                func.count(IvPointRow.series_id),
                func.min(IvPointRow.point_date),
                func.max(IvPointRow.point_date),
                func.max(HistorySeries.synced_at),
            )
            .select_from(HistorySeries)
            .outerjoin(IvPointRow, IvPointRow.series_id == HistorySeries.id)
            .where(HistorySeries.dataset == "iv")
        )
    ).one()
    result["iv"] = {
        "series": iv[0],
        "rows": iv[1],
        "oldest": iv[2].isoformat() if iv[2] else None,
        "newest": iv[3].isoformat() if iv[3] else None,
        "newest_synced_at": iv[4].isoformat() if iv[4] else None,
    }
    return result


async def clear(
    session: AsyncSession,
    dataset: str,
    symbol: str | None = None,
    provider: str | None = None,
    interval: str | None = None,
) -> dict[str, int]:
    """Delete matching series with their rows; returns deleted series and rows."""
    conditions = []
    if dataset != "all":
        conditions.append(HistorySeries.dataset == dataset)
    if symbol:
        conditions.append(HistorySeries.symbol == symbol)
    if provider:
        conditions.append(HistorySeries.provider == provider)
    if interval:
        conditions.append(HistorySeries.dataset == "prices")
        conditions.append(HistorySeries.interval == interval)
    ids = list(
        (await session.execute(select(HistorySeries.id).where(*conditions))).scalars()
    )
    if not ids:
        return {"series": 0, "rows": 0}
    rows = 0
    for table, column in (
        (PriceBarRow, PriceBarRow.series_id),
        (IvPointRow, IvPointRow.series_id),
    ):
        outcome: Any = await session.execute(delete(table).where(column.in_(ids)))
        rows += outcome.rowcount or 0
    await session.execute(delete(HistorySeries).where(HistorySeries.id.in_(ids)))
    return {"series": len(ids), "rows": int(rows)}


async def covering_price_series(
    session: AsyncSession,
    symbol: str,
    exclude_provider: str,
    start: datetime,
) -> list[Series]:
    """Daily price series of other providers that start at or before `start`."""
    rows = (
        await session.execute(
            select(HistorySeries)
            .where(
                HistorySeries.dataset == "prices",
                HistorySeries.interval == "1d",
                HistorySeries.extended_hours.is_(False),
                HistorySeries.symbol == symbol,
                HistorySeries.provider != exclude_provider,
                HistorySeries.covered_from.is_not(None),
                HistorySeries.covered_from <= start,
            )
            .order_by(HistorySeries.synced_at.desc().nulls_last())
        )
    ).scalars()
    return [_series(row) for row in rows]
