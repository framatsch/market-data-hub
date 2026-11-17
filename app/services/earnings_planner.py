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

"""Pure request-driven refresh policy of earnings data (design D5)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

CALENDAR_HORIZON_DAYS = 365
ACTUALS_RESYNC = timedelta(hours=12)


@dataclass(frozen=True)
class SyncInfo:
    synced_at: datetime | None = None
    failed_at: datetime | None = None
    covered_to: date | None = None


@dataclass(frozen=True)
class HistoryInput:
    symbol: str
    sync: SyncInfo | None
    # A stored event within the actuals window still lacks its actual EPS.
    unreported_recent: bool = False


@dataclass(frozen=True)
class RefreshPlan:
    calendar_due: bool
    history_due: tuple[str, ...]
    history_pending: tuple[str, ...]
    history_paused: tuple[str, ...]


def _paused(sync: SyncInfo | None, now: datetime, retry: timedelta) -> bool:
    return (
        sync is not None
        and sync.failed_at is not None
        and now - sync.failed_at < retry
    )


def calendar_due(
    *,
    now: datetime,
    today: date,
    request_end: date,
    calendar: SyncInfo | None,
    resync: timedelta,
    retry: timedelta,
) -> bool:
    if _paused(calendar, now, retry):
        return False
    if calendar is None or calendar.synced_at is None:
        return True
    if now - calendar.synced_at >= resync:
        return True
    needed_end = min(request_end, today + timedelta(days=CALENDAR_HORIZON_DAYS))
    return calendar.covered_to is None or needed_end > calendar.covered_to


def plan_refresh(
    *,
    now: datetime,
    today: date,
    request_end: date,
    needs_calendar: bool,
    needs_history: bool,
    calendar: SyncInfo | None,
    symbols: Sequence[HistoryInput],
    budget_remaining: int | None,
    calendar_resync: timedelta,
    retry: timedelta,
) -> RefreshPlan:
    """Decide which provider requests a call needs.

    The calendar is one request for all symbols and has priority over history;
    due history is served in request order until the budget is used up.
    """
    due_calendar = needs_calendar and calendar_due(
        now=now,
        today=today,
        request_end=request_end,
        calendar=calendar,
        resync=calendar_resync,
        retry=retry,
    )
    due: list[str] = []
    paused: list[str] = []
    if needs_history:
        for item in symbols:
            if _paused(item.sync, now, retry):
                paused.append(item.symbol)
            elif (
                item.sync is None
                or item.sync.synced_at is None
                or (
                    item.unreported_recent
                    and now - item.sync.synced_at > ACTUALS_RESYNC
                )
            ):
                due.append(item.symbol)
    slots = (
        None
        if budget_remaining is None
        else max(0, budget_remaining - (1 if due_calendar else 0))
    )
    if slots is None:
        selected, pending = due, []
    else:
        selected, pending = due[:slots], due[slots:]
    return RefreshPlan(
        calendar_due=due_calendar,
        history_due=tuple(selected),
        history_pending=tuple(pending),
        history_paused=tuple(paused),
    )
