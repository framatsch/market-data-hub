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

"""Database access of stored earnings events (design D4); events never mix providers."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

from sqlalchemy import and_, delete, exists, select, text, true
from sqlalchemy import update as sql_update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.earnings import EarningsEvent
from app.store.models import EarningsEventRow, EarningsSync

CALENDAR_SCOPE = "calendar"
DAY_SCOPE_PREFIX = "calendar-day:"
DAY_REPLACE_WINDOW_DAYS = 60
_LOCK_NAMESPACE = 7205


@dataclass(frozen=True)
class SyncState:
    provider: str
    scope: str
    covered_from: date | None
    covered_to: date | None
    synced_at: datetime | None
    sync_failed_at: datetime | None
    invalidated_at: datetime | None = None


async def lock_scope(session: AsyncSession, provider: str, scope: str) -> None:
    """Transaction-scoped advisory lock: replicas cannot interleave a replace."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:ns, hashtext(:key))"),
        {"ns": _LOCK_NAMESPACE, "key": f"{provider}:{scope}"},
    )


def _event(row: EarningsEventRow) -> EarningsEvent:
    return EarningsEvent(
        symbol=row.symbol,
        report_date=row.report_date,
        report_time=row.report_time,  # type: ignore[arg-type]
        date_status=row.date_status,  # type: ignore[arg-type]
        reported=row.reported,
        fiscal_period_end=row.fiscal_period_end,
        eps_estimate=row.eps_estimate,
        eps_actual=row.eps_actual,
        eps_surprise=row.eps_surprise,
        eps_surprise_pct=row.eps_surprise_pct,
        revenue_estimate=row.revenue_estimate,
        revenue_actual=row.revenue_actual,
        currency=row.currency,
        provider=row.provider,
        updated_at=row.updated_at,
    )


def _values(
    provider: str, event: EarningsEvent, source: str, now: datetime
) -> dict[str, Any]:
    return {
        "provider": provider,
        "symbol": event.symbol,
        "report_date": event.report_date,
        "source": source,
        "report_time": event.report_time,
        "date_status": event.date_status,
        "reported": event.reported,
        "fiscal_period_end": event.fiscal_period_end,
        "eps_estimate": event.eps_estimate,
        "eps_actual": event.eps_actual,
        "eps_surprise": event.eps_surprise,
        "eps_surprise_pct": event.eps_surprise_pct,
        "revenue_estimate": event.revenue_estimate,
        "revenue_actual": event.revenue_actual,
        "currency": event.currency,
        "first_seen_at": now,
        "updated_at": now,
    }


async def read_events(
    session: AsyncSession,
    provider: str,
    symbols: Iterable[str] | None,
    start: date,
    end: date,
) -> list[EarningsEvent]:
    """Stored events of one provider in the inclusive range, ordered by date and symbol."""
    query = select(EarningsEventRow).where(
        EarningsEventRow.provider == provider,
        EarningsEventRow.report_date >= start,
        EarningsEventRow.report_date <= end,
    )
    if symbols is not None:
        query = query.where(EarningsEventRow.symbol.in_(list(symbols)))
    rows = await session.execute(
        query.order_by(EarningsEventRow.report_date, EarningsEventRow.symbol)
    )
    return [_event(row) for row in rows.scalars()]


async def known_symbols(
    session: AsyncSession, provider: str, symbols: Iterable[str]
) -> set[str]:
    """Symbols with at least one stored event of any date."""
    rows = await session.execute(
        select(EarningsEventRow.symbol)
        .where(
            EarningsEventRow.provider == provider,
            EarningsEventRow.symbol.in_(list(symbols)),
        )
        .distinct()
    )
    return set(rows.scalars())


async def get_sync(
    session: AsyncSession, provider: str, scope: str
) -> SyncState | None:
    row = await session.get(EarningsSync, (provider, scope))
    if row is None:
        return None
    return SyncState(
        provider,
        scope,
        row.covered_from,
        row.covered_to,
        row.synced_at,
        row.sync_failed_at,
        row.invalidated_at,
    )


async def get_syncs(
    session: AsyncSession, provider: str, scopes: Iterable[str]
) -> dict[str, SyncState]:
    rows = await session.execute(
        select(EarningsSync).where(
            EarningsSync.provider == provider, EarningsSync.scope.in_(list(scopes))
        )
    )
    return {
        row.scope: SyncState(
            provider,
            row.scope,
            row.covered_from,
            row.covered_to,
            row.synced_at,
            row.sync_failed_at,
            row.invalidated_at,
        )
        for row in rows.scalars()
    }


async def mark_failed(
    session: AsyncSession, provider: str, scope: str, now: datetime | None = None
) -> None:
    now = now or datetime.now(UTC)
    await session.execute(
        insert(EarningsSync)
        .values(provider=provider, scope=scope, sync_failed_at=now)
        .on_conflict_do_update(
            index_elements=["provider", "scope"], set_={"sync_failed_at": now}
        )
    )


async def _mark_synced(
    session: AsyncSession,
    provider: str,
    scope: str,
    now: datetime,
    covered_from: date | None,
    covered_to: date | None,
) -> None:
    values = {
        "covered_from": covered_from,
        "covered_to": covered_to,
        "synced_at": now,
        "sync_failed_at": None,
    }
    await session.execute(
        insert(EarningsSync)
        .values(provider=provider, scope=scope, **values)
        .on_conflict_do_update(index_elements=["provider", "scope"], set_=values)
    )


async def drop_reconciled_calendar_rows(
    session: AsyncSession, provider: str, symbol: str | None = None
) -> None:
    """Remove calendar rows whose quarter a history row reports with an actual EPS."""
    history = aliased(EarningsEventRow)
    await session.execute(
        delete(EarningsEventRow)
        .where(
            EarningsEventRow.provider == provider,
            EarningsEventRow.source == "calendar",
            EarningsEventRow.fiscal_period_end.is_not(None),
            *([EarningsEventRow.symbol == symbol] if symbol is not None else []),
            exists().where(
                and_(
                    history.provider == EarningsEventRow.provider,
                    history.symbol == EarningsEventRow.symbol,
                    history.source == "history",
                    history.fiscal_period_end == EarningsEventRow.fiscal_period_end,
                    history.eps_actual.is_not(None),
                )
            ),
        )
        .execution_options(synchronize_session=False)
    )


async def replace_calendar(
    session: AsyncSession,
    provider: str,
    events: list[EarningsEvent],
    covered_from: date,
    covered_to: date,
    now: datetime | None = None,
) -> None:
    """Replace the provider's calendar rows in the covered range (one transaction).

    The caller runs this in one `session_scope`. A moved report date therefore
    replaces its old row; rows of other providers and history rows stay.
    """
    now = now or datetime.now(UTC)
    await lock_scope(session, provider, CALENDAR_SCOPE)
    await session.execute(
        delete(EarningsEventRow).where(
            EarningsEventRow.provider == provider,
            EarningsEventRow.source == "calendar",
            EarningsEventRow.report_date >= covered_from,
            EarningsEventRow.report_date <= covered_to,
        )
    )
    unique = {(e.symbol, e.report_date): e for e in events}
    rows = [_values(provider, e, "calendar", now) for e in unique.values()]
    for offset in range(0, len(rows), 1000):
        # A history row for the same date keeps precedence over the calendar row.
        await session.execute(
            insert(EarningsEventRow)
            .values(rows[offset : offset + 1000])
            .on_conflict_do_nothing(
                index_elements=["provider", "symbol", "report_date"]
            )
        )
    await drop_reconciled_calendar_rows(session, provider)
    await _mark_synced(session, provider, CALENDAR_SCOPE, now, covered_from, covered_to)


def day_scope(day: date) -> str:
    return f"{DAY_SCOPE_PREFIX}{day.isoformat()}"


async def replace_day(
    session: AsyncSession,
    provider: str,
    day: date,
    events: list[EarningsEvent],
    today: date,
    now: datetime | None = None,
) -> None:
    """Replace everything a provider stored for one date (one transaction).

    The day calendar is authoritative for its date: all of the provider's events of
    the day go, the delivered ones are inserted. Another upcoming event of a listed
    symbol within 60 days is a moved date and goes too. A symbol that was listed
    before but is gone now has its symbol synchronisation invalidated.
    """
    now = now or datetime.now(UTC)
    scope = day_scope(day)
    await lock_scope(session, provider, scope)
    before = set(
        (
            await session.execute(
                select(EarningsEventRow.symbol).where(
                    EarningsEventRow.provider == provider,
                    EarningsEventRow.report_date == day,
                )
            )
        ).scalars()
    )
    await session.execute(
        delete(EarningsEventRow).where(
            EarningsEventRow.provider == provider, EarningsEventRow.report_date == day
        )
    )
    unique = {e.symbol: e for e in events}
    rows = [_values(provider, e, "calendar", now) for e in unique.values()]
    for offset in range(0, len(rows), 1000):
        await session.execute(
            insert(EarningsEventRow)
            .values(rows[offset : offset + 1000])
            .on_conflict_do_nothing(
                index_elements=["provider", "symbol", "report_date"]
            )
        )
    window = timedelta(days=DAY_REPLACE_WINDOW_DAYS)
    for offset in range(0, len(unique), 500):
        listed = list(unique)[offset : offset + 500]
        await session.execute(
            delete(EarningsEventRow).where(
                EarningsEventRow.provider == provider,
                EarningsEventRow.symbol.in_(listed),
                EarningsEventRow.reported.is_(False),
                EarningsEventRow.report_date >= today,
                EarningsEventRow.report_date != day,
                EarningsEventRow.report_date >= day - window,
                EarningsEventRow.report_date <= day + window,
            )
        )
    gone = sorted(before - set(unique))
    if gone:
        await session.execute(
            sql_update(EarningsSync)
            .where(EarningsSync.provider == provider, EarningsSync.scope.in_(gone))
            .values(invalidated_at=now)
        )
    await _mark_synced(session, provider, scope, now, day, day)


async def upsert_history(
    session: AsyncSession,
    provider: str,
    symbol: str,
    events: list[EarningsEvent],
    now: datetime | None = None,
    prune_upcoming_from: date | None = None,
) -> None:
    """Insert or update a symbol's events; first_seen_at is preserved.

    With `prune_upcoming_from` (providers answering per symbol) the response is
    authoritative for the future: the provider's stored events of the symbol on or
    after that date which are not in the response are deleted, and an earlier
    invalidation by a day calendar is cleared.
    """
    now = now or datetime.now(UTC)
    await lock_scope(session, provider, symbol)
    for event in events:
        values = _values(provider, event, "history", now)
        update = {
            key: values[key]
            for key in values
            if key not in {"provider", "symbol", "report_date", "first_seen_at"}
        }
        await session.execute(
            insert(EarningsEventRow)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["provider", "symbol", "report_date"], set_=update
            )
        )
    if prune_upcoming_from is not None:
        keep = {event.report_date for event in events}
        await session.execute(
            delete(EarningsEventRow).where(
                EarningsEventRow.provider == provider,
                EarningsEventRow.symbol == symbol,
                EarningsEventRow.report_date >= prune_upcoming_from,
                EarningsEventRow.report_date.not_in(keep) if keep else true(),
            )
        )
    await drop_reconciled_calendar_rows(session, provider, symbol)
    await _mark_synced(session, provider, symbol, now, None, None)
    if prune_upcoming_from is not None:
        await session.execute(
            sql_update(EarningsSync)
            .where(EarningsSync.provider == provider, EarningsSync.scope == symbol)
            .values(invalidated_at=None)
        )


async def clear(session: AsyncSession, provider: str | None = None) -> int:
    query = delete(EarningsEventRow)
    sync = delete(EarningsSync)
    if provider is not None:
        query = query.where(EarningsEventRow.provider == provider)
        sync = sync.where(EarningsSync.provider == provider)
    result = await session.execute(query)
    await session.execute(sync)
    return int(cast(CursorResult[Any], result).rowcount or 0)
