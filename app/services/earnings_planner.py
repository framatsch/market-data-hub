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
DAY_RESYNC = timedelta(hours=20)
DAY_REFRESH_AHEAD_WEEKDAYS = 2


@dataclass(frozen=True)
class SyncInfo:
    synced_at: datetime | None = None
    failed_at: datetime | None = None
    covered_to: date | None = None
    invalidated_at: datetime | None = None


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


# --------------------------------------------------------------- day window


def _is_weekday(day: date) -> bool:
    return day.weekday() < 5


def previous_weekday(day: date) -> date:
    day -= timedelta(days=1)
    while not _is_weekday(day):
        day -= timedelta(days=1)
    return day


def next_weekdays(day: date, count: int) -> list[date]:
    """The `count` weekdays strictly after `day`."""
    result: list[date] = []
    while len(result) < count:
        day += timedelta(days=1)
        if _is_weekday(day):
            result.append(day)
    return result


def window_days(today: date, weekdays: int) -> list[date]:
    """Previous weekday, today (when a weekday), then `weekdays` weekdays ahead."""
    days = [previous_weekday(today)]
    if _is_weekday(today):
        days.append(today)
    return [*days, *next_weekdays(today, weekdays)]


@dataclass(frozen=True)
class DayPlan:
    due: tuple[date, ...]
    pending: tuple[date, ...]
    paused: tuple[date, ...]


def plan_days(
    *,
    now: datetime,
    today: date,
    weekdays: int,
    syncs: dict[date, SyncInfo],
    retry: timedelta,
    budget_remaining: int | None,
) -> DayPlan:
    """Days of the window that need a provider request, in date order.

    A day is due without a successful synchronisation, or when it is the previous
    weekday, today or one of the next two weekdays and was synchronised more than
    20 hours ago. Days paused after a failure are skipped; days beyond the budget
    are pending.
    """
    days = window_days(today, weekdays)
    refresh = {previous_weekday(today), today, *next_weekdays(today, DAY_REFRESH_AHEAD_WEEKDAYS)}
    due: list[date] = []
    paused: list[date] = []
    for day in days:
        sync = syncs.get(day)
        if _paused(sync, now, retry):
            paused.append(day)
        elif sync is None or sync.synced_at is None or (
            day in refresh and now - sync.synced_at > DAY_RESYNC
        ):
            due.append(day)
    if budget_remaining is None:
        return DayPlan(tuple(due), (), tuple(paused))
    return DayPlan(tuple(due[:budget_remaining]), tuple(due[budget_remaining:]), tuple(paused))


# ---------------------------------------------------------- per-symbol plan


@dataclass(frozen=True)
class SymbolInput:
    symbol: str
    sync: SyncInfo | None
    # Latest stored event date (any state), None when nothing is stored.
    latest_event: date | None = None
    # Stored event on or after today.
    has_upcoming: bool = False
    # Stored event dated today or later within the synchronised day window.
    in_window: bool = False
    # Stored event within the actuals window still lacks its actual EPS.
    unreported_recent: bool = False


@dataclass(frozen=True)
class SymbolPlan:
    due: tuple[str, ...]
    pending: tuple[str, ...]
    paused: tuple[str, ...]


def symbol_due(
    item: SymbolInput,
    *,
    now: datetime,
    needs_past: bool,
    needs_next: bool,
    has_day_calendar: bool,
    resync: timedelta,
) -> bool:
    """Rules (a)-(d) of the per-symbol refresh; only (a) depends on what the request needs.

    `has_day_calendar` means a day calendar keeps the actuals current *in this
    request*; a request that does not consult the window (for example `kind=reported`
    or the history role of a composed response) passes False so that rule (d) applies.
    """
    sync = item.sync
    if sync is None or sync.synced_at is None:
        # (a) never synchronised: needs its past, or its next event the window lacks.
        return needs_past or (needs_next and not item.in_window)
    if sync.invalidated_at is not None:  # (c) a day calendar removed its event
        return True
    if not item.has_upcoming and (  # (b)
        (item.latest_event is not None and sync.synced_at.date() < item.latest_event)
        or now - sync.synced_at > resync
    ):
        return True
    return (  # (d) no day calendar: wait for the actuals
        not has_day_calendar
        and item.unreported_recent
        and now - sync.synced_at > ACTUALS_RESYNC
    )


def plan_symbols(
    *,
    now: datetime,
    symbols: Sequence[SymbolInput],
    needs_past: bool,
    needs_next: bool,
    has_day_calendar: bool,
    resync: timedelta,
    retry: timedelta,
    budget_remaining: int | None,
) -> SymbolPlan:
    due: list[str] = []
    paused: list[str] = []
    for item in symbols:
        if _paused(item.sync, now, retry):
            paused.append(item.symbol)
        elif symbol_due(
            item, now=now, needs_past=needs_past, needs_next=needs_next,
            has_day_calendar=has_day_calendar, resync=resync,
        ):
            due.append(item.symbol)
    if budget_remaining is None:
        return SymbolPlan(tuple(due), (), tuple(paused))
    return SymbolPlan(
        tuple(due[:budget_remaining]), tuple(due[budget_remaining:]), tuple(paused)
    )
