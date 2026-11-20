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

"""Earnings calendar, next earnings and company history (design D3-D6, D8, D9)."""

import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app import response_meta
from app.config import settings
from app.models.earnings import (
    EarningsEvent,
    EarningsSymbolStatus,
    NextEarnings,
    earnings_today,
)
from app.observability.telemetry import bind_data_provider, current_telemetry
from app.observability.telemetry import span as telemetry_span
from app.providers.base import (
    BaseEarningsHistoryProvider,
    BaseEarningsProvider,
    BaseEarningsUpcomingProvider,
)
from app.providers.registry import ProviderRegistry, get_registry
from app.providers.request_budget import budget_redis
from app.services.earnings_planner import (
    CALENDAR_HORIZON_DAYS,
    HistoryInput,
    SymbolInput,
    SyncInfo,
    calendar_due,
    plan_days,
    plan_refresh,
    plan_symbols,
    window_days,
)
from app.store import earnings_repository as repo
from app.store import engine
from app.utils.errors import (
    AppError,
    CapabilityNotSupportedError,
    DataNotFoundError,
    DataValidationError,
    ProviderQuotaExhaustedError,
)
from app.utils.symbols import ParsedSymbol, SecType, parse_symbol

logger = logging.getLogger(__name__)

MAX_SYMBOLS = 50
MAX_RANGE_DAYS = 800
HISTORY_LOOKBACK_DAYS = 1095
EARNINGS_TYPES: frozenset[SecType] = frozenset({"stock", "etf"})
CALENDAR_KEY = "mdh:earnings:provider-calendar:{provider}:12month"
DAY_KEY = "mdh:earnings:provider-day:{provider}:{day}"
SYMBOL_KEY = "mdh:earnings:provider-symbol:{provider}:{root}"
DAY_KEY_TTL = 7 * 86400
PLANNER_SPAN_DAYS = 400

# The hub only knows an instrument as ETF from an explicit sec_type. Well-known
# ETF tickers are therefore answered as not applicable without a provider call;
# an unlisted ETF just has no earnings data at the provider.
KNOWN_ETFS = frozenset(
    ["SPY", "QQQ", "IWM", "DIA", "VOO", "VTI", "IVV", "EEM", "EFA", "VEA", "VWO", "GLD", "SLV", "TLT", "IEF", "SHY", "HYG", "LQD", "AGG", "BND", "XLF", "XLK", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB", "XLRE", "XLC", "SMH", "SOXX", "XBI", "IBB", "KRE", "XOP", "GDX", "GDXJ", "ARKK", "ARKW", "VXX", "UVXY", "SVXY", "SQQQ", "TQQQ", "SPXL", "SPXS", "UPRO", "SDS", "USO", "UNG", "IBIT", "BITO", "RSP", "MDY", "IJH", "IJR", "SCHD", "JEPI", "VNQ", "VUG", "VTV", "QQQM", "SPLG", "SPYG", "SPYV"]
)


def is_etf(symbol: ParsedSymbol) -> bool:
    return symbol.sec_type == "etf" or symbol.root in KNOWN_ETFS


def parse_symbol_list(raw: str | list[str]) -> list[ParsedSymbol]:
    """Comma-separated symbols, de-duplicated in request order; stocks and ETFs only."""
    parts = raw.split(",") if isinstance(raw, str) else raw
    parsed: dict[str, ParsedSymbol] = {}
    for part in (item.strip() for item in parts):
        if not part:
            continue
        try:
            symbol = parse_symbol(part, allowed=EARNINGS_TYPES)
        except DataValidationError as exc:
            if "sec_type" in exc.details and "supported" in exc.details:
                raise DataValidationError(
                    f"Earnings are only available for stocks; {part!r} is not supported",
                    {**exc.details, "symbol": part},
                ) from exc
            raise
        parsed.setdefault(symbol.canonical, symbol)
    if not parsed:
        raise DataValidationError("At least one symbol is required", {"symbols": raw})
    if len(parsed) > MAX_SYMBOLS:
        raise DataValidationError(
            f"At most {MAX_SYMBOLS} distinct symbols are allowed",
            {"count": len(parsed), "max": MAX_SYMBOLS},
        )
    return list(parsed.values())


def reconcile_events(events: list[EarningsEvent]) -> list[EarningsEvent]:
    """One event per symbol and fiscal period; an actual EPS decides the winner."""
    groups: dict[tuple[str, date | None, str], list[EarningsEvent]] = defaultdict(list)
    for event in events:
        key = (
            event.symbol,
            event.fiscal_period_end,
            "" if event.fiscal_period_end else event.report_date.isoformat(),
        )
        groups[key].append(event)
    result = []
    for group in groups.values():
        actual = [event for event in group if event.eps_actual is not None]
        pool = actual or group
        winner = max(pool, key=lambda e: (e.updated_at, e.report_date))
        if winner.revenue_actual is None:
            # Reported revenue is kept even when another source won on EPS.
            donor = next((e for e in group if e.revenue_actual is not None), None)
            if donor is not None:
                winner = winner.model_copy(update={"revenue_actual": donor.revenue_actual})
        result.append(winner)
    return sorted(result, key=lambda e: (e.report_date, e.symbol))


@dataclass
class EarningsResult:
    provider: str | None
    events: list[EarningsEvent]
    symbols: list[EarningsSymbolStatus]
    # Set for a composed response: {"upcoming": name, "history": name}.
    providers: dict[str, str] | None = None


@dataclass
class NextResult:
    provider: str | None
    rows: list[NextEarnings]
    providers: dict[str, str] | None = None


@dataclass
class _Roles:
    upcoming: BaseEarningsProvider | None
    history: BaseEarningsProvider | None
    missing: dict[str, str]  # role -> message for symbols


@dataclass
class _Snapshot:
    events: list[EarningsEvent]
    calendar: SyncInfo | None
    syncs: dict[str, SyncInfo]
    known: set[str]
    unreported: set[str]


@dataclass
class _Gathered:
    events: list[EarningsEvent]
    history: dict[str, str]
    known: set[str]
    errors: dict[str, AppError] = field(default_factory=dict)
    not_found: set[str] = field(default_factory=set)
    pending_reason: dict[str, str] = field(default_factory=dict)
    # History skipped because the budget was used up (nothing was sent upstream).
    budget_errors: dict[str, AppError] = field(default_factory=dict)
    calendar_error: AppError | None = None
    calendar_available: bool = True
    used_store: bool = False
    from_store: bool = False
    from_provider: bool = False
    from_redis: bool = False


def _record_sources(*gathers: _Gathered | None, stored_report: bool = False) -> None:
    telemetry = current_telemetry()
    if telemetry is None:
        return
    results = [gathered for gathered in gathers if gathered is not None]
    from_store = stored_report or any(result.from_store for result in results)
    from_provider = any(result.from_provider for result in results)
    if from_store:
        telemetry.store_outcome = (
            "stale" if response_meta.current().stale else "partial" if from_provider else "hit"
        )
    elif any(result.used_store for result in results):
        telemetry.store_outcome = "miss"
    if not from_store and not from_provider:
        telemetry.earnings_fallback_hit = any(result.from_redis for result in results)


def _kept_stored_event(
    previous: list[EarningsEvent], current: list[EarningsEvent], fetched: list[EarningsEvent],
    start: date, end: date,
) -> bool:
    def identity(event: EarningsEvent) -> tuple[str, date, date | None]:
        return event.symbol, event.report_date, event.fiscal_period_end

    retained = {identity(event) for event in previous} - {identity(event) for event in fetched}
    return any(
        start <= event.report_date <= end and identity(event) in retained
        for event in current
    )


@dataclass
class _SymState:
    store: bool
    events: list[EarningsEvent] = field(default_factory=list)
    day_syncs: dict[date, SyncInfo] = field(default_factory=dict)
    symbol_syncs: dict[str, SyncInfo] = field(default_factory=dict)
    known: set[str] = field(default_factory=set)
    eph_days: dict[date, list[EarningsEvent]] = field(default_factory=dict)
    eph_symbols: dict[str, list[EarningsEvent]] = field(default_factory=dict)


def _sync_info(state: repo.SyncState | None) -> SyncInfo | None:
    if state is None:
        return None
    return SyncInfo(state.synced_at, state.sync_failed_at, state.covered_to, state.invalidated_at)


def _is_symbol_provider(provider: BaseEarningsProvider) -> bool:
    return isinstance(provider, BaseEarningsUpcomingProvider) and provider.upcoming_mode == "symbol"


def merge_ephemeral(
    days: dict[date, list[EarningsEvent]],
    symbols: dict[str, list[EarningsEvent]],
    today: date,
) -> list[EarningsEvent]:
    """Store-less counterpart of the replacement rules: a day calendar wins for its date."""
    listed = {event.symbol: day for day, events in days.items() for event in events}
    result = [event for events in days.values() for event in events]
    for root, events in symbols.items():
        for event in events:
            if event.report_date in days:
                continue
            day = listed.get(root)
            if (
                day is not None
                and not event.reported
                and event.report_date >= today
                and abs((event.report_date - day).days) <= repo.DAY_REPLACE_WINDOW_DAYS
            ):
                continue
            result.append(event)
    return result


def _is_calendar_provider(provider: BaseEarningsProvider) -> bool:
    return isinstance(provider, BaseEarningsUpcomingProvider) and provider.upcoming_mode == "calendar"


class EarningsService:
    def __init__(self, registry: ProviderRegistry | None = None) -> None:
        self.registry = registry or get_registry()
        self._locks: dict[str, asyncio.Lock] = {}

    # ----------------------------------------------------------- store access

    async def _store_call(
        self, work: Callable[[AsyncSession], Awaitable[object]]
    ) -> bool:
        async def run() -> bool:
            async with engine.session_scope(operation="write") as session:
                await work(session)
            return True

        return bool(await engine.guarded(run, False))

    async def _read_events(
        self, provider: str, roots: list[str], start: date, end: date
    ) -> list[EarningsEvent] | None:
        async def load() -> list[EarningsEvent]:
            async with engine.session_scope(operation="read") as session:
                return await repo.read_events(session, provider, roots, start, end)

        return await engine.guarded(load, None)

    async def _read_snapshot(
        self, provider: str, roots: list[str], start: date, end: date, today: date
    ) -> _Snapshot | None:
        window_start = today - timedelta(days=settings.EARNINGS_ACTUALS_WINDOW_DAYS)

        async def load() -> _Snapshot:
            async with engine.session_scope(operation="read") as session:
                events = await repo.read_events(
                    session, provider, roots, min(start, window_start), end
                )
                syncs = await repo.get_syncs(
                    session, provider, [repo.CALENDAR_SCOPE, *roots]
                )
                known = await repo.known_symbols(session, provider, roots)
            unreported = {
                event.symbol
                for event in events
                if event.eps_actual is None
                and window_start <= event.report_date <= today
            }
            calendar = _sync_info(syncs.pop(repo.CALENDAR_SCOPE, None))
            return _Snapshot(
                events,
                calendar,
                {root: info for root, state in syncs.items() if (info := _sync_info(state))},
                known,
                unreported,
            )

        return await engine.guarded(load, None)

    # -------------------------------------------------------- ephemeral cache

    async def _cached_calendar(
        self, provider: str
    ) -> tuple[list[EarningsEvent], datetime] | None:
        redis = budget_redis()
        if redis is None:
            return None
        try:
            async with telemetry_span("redis", "read"):
                raw = await redis.get(CALENDAR_KEY.format(provider=provider))
            if not raw:
                return None
            payload = json.loads(raw)
            return (
                [EarningsEvent.model_validate(item) for item in payload["events"]],
                datetime.fromisoformat(payload["fetched_at"]),
            )
        except Exception:
            logger.debug("Earnings calendar cache unavailable", exc_info=True)
            return None

    async def _cache_calendar(
        self, provider: str, events: list[EarningsEvent], fetched_at: datetime
    ) -> None:
        redis = budget_redis()
        if redis is None:
            return
        try:
            payload = {
                "fetched_at": fetched_at.isoformat(),
                "events": [event.model_dump(mode="json") for event in events],
            }
            async with telemetry_span("redis-write", "write"):
                await redis.set(
                    CALENDAR_KEY.format(provider=provider),
                    json.dumps(payload),
                    ex=settings.EARNINGS_CALENDAR_RESYNC_HOURS * 3600,
                )
        except Exception:
            logger.debug("Earnings calendar cache write failed", exc_info=True)

    async def _quota_error(self, provider: BaseEarningsProvider) -> AppError:
        budget = getattr(provider, "budget", None)
        period, limit = "day", 0
        if budget is not None:
            usage = await budget.usage()
            month_hit = usage["month"]["budget"] and usage["month"]["used"] >= usage["month"]["budget"]
            period = "month" if month_hit and not usage["day_exhausted"] else "day"
            limit = usage[period]["budget"]
        return ProviderQuotaExhaustedError(provider.name, period, limit)

    # ------------------------------------------------------------- the engine

    async def _gather(
        self,
        provider: BaseEarningsProvider,
        roots: list[str],
        start: date,
        end: date,
        *,
        fetch_history: bool,
        read_start: date,
        read_end: date,
        fetch_upcoming: bool = True,
    ) -> _Gathered:
        if not roots:
            return _Gathered([], {}, set())
        lock = self._locks.setdefault(provider.name, asyncio.Lock())
        async with lock:
            return await self._gather_locked(
                provider, roots, start, end, fetch_history, read_start, read_end,
                fetch_upcoming,
            )

    async def _gather_locked(
        self,
        provider: BaseEarningsProvider,
        roots: list[str],
        start: date,
        end: date,
        fetch_history: bool,
        read_start: date,
        read_end: date,
        fetch_upcoming: bool = True,
    ) -> _Gathered:
        if _is_symbol_provider(provider):
            return await self._gather_symbol_mode(
                provider, roots, start, end, fetch_history, fetch_upcoming, read_start, read_end
            )
        name = provider.name
        today = earnings_today()
        now = datetime.now(UTC)
        needs_calendar = fetch_upcoming and _is_calendar_provider(provider) and read_end >= today
        needs_history = fetch_history and start < today
        snapshot = await self._read_snapshot(name, roots, read_start, read_end, today)
        cached = None
        if snapshot is not None:
            calendar_sync = snapshot.calendar
        else:
            cached = await self._cached_calendar(name)
            calendar_sync = (
                SyncInfo(cached[1], None, today + timedelta(days=CALENDAR_HORIZON_DAYS))
                if cached
                else None
            )
        budget = getattr(provider, "budget", None)
        remaining = await budget.remaining() if budget is not None else None
        plan = plan_refresh(
            now=now,
            today=today,
            request_end=read_end,
            needs_calendar=needs_calendar,
            needs_history=needs_history,
            calendar=calendar_sync,
            symbols=[
                HistoryInput(
                    root,
                    snapshot.syncs.get(root) if snapshot else None,
                    root in snapshot.unreported if snapshot else False,
                )
                for root in roots
            ],
            budget_remaining=remaining,
            calendar_resync=timedelta(hours=settings.EARNINGS_CALENDAR_RESYNC_HOURS),
            retry=timedelta(minutes=settings.EARNINGS_RETRY_MINUTES),
        )

        result = _Gathered([], {}, set())
        fetched_calendar: list[EarningsEvent] | None = None
        fetched_history: dict[str, list[EarningsEvent]] = {}
        wrote = False
        quota_hit = False

        if plan.calendar_due:
            try:
                fetched_calendar = await cast(BaseEarningsUpcomingProvider, provider).get_upcoming_earnings(
                    today, today + timedelta(days=CALENDAR_HORIZON_DAYS), None
                )
                if snapshot is not None:
                    wrote |= await self._store_call(
                        lambda s: repo.replace_calendar(
                            s, name, fetched_calendar or [], today,
                            today + timedelta(days=CALENDAR_HORIZON_DAYS), now,
                        )
                    )
                else:
                    await self._cache_calendar(name, fetched_calendar, now)
            except AppError as exc:
                result.calendar_error = exc
                if snapshot is not None:
                    await self._store_call(
                        lambda s: repo.mark_failed(s, name, repo.CALENDAR_SCOPE, now)
                    )

        attempted: list[str] = []
        for root in plan.history_due:
            attempted.append(root)
            try:
                events = await cast(BaseEarningsHistoryProvider, provider).get_earnings_history(root)
            except DataNotFoundError:
                events = []
                result.not_found.add(root)
            except AppError as exc:
                result.errors[root] = exc
                if exc.code == "PROVIDER_QUOTA_EXHAUSTED":
                    quota_hit = True
                    result.pending_reason[root] = "provider request budget exhausted"
                    break
                if snapshot is not None:
                    await self._store_call(
                        partial(repo.mark_failed, provider=name, scope=root, now=now)
                    )
                continue
            fetched_history[root] = events
            if snapshot is not None:
                wrote |= await self._store_call(
                    partial(repo.upsert_history, provider=name, symbol=root, events=events, now=now)
                )
        skipped = [
            *(root for root in plan.history_due if quota_hit and root not in attempted),
            *plan.history_pending,
        ]
        if skipped:
            quota = await self._quota_error(provider)
            for root in skipped:
                result.pending_reason[root] = "provider request budget exhausted"
                result.budget_errors[root] = quota

        events = await self._compose(
            name, roots, read_start, read_end, snapshot, cached, fetched_calendar,
            fetched_history, wrote,
        )
        result.events = reconcile_events(events)
        result.used_store = snapshot is not None
        result.from_provider = fetched_calendar is not None or bool(fetched_history)
        result.from_redis = cached is not None and needs_calendar and fetched_calendar is None
        if snapshot is not None and current_telemetry() is not None:
            result.from_store = not result.from_provider or _kept_stored_event(
                snapshot.events, result.events,
                [*(fetched_calendar or []), *(e for batch in fetched_history.values() for e in batch)],
                read_start, read_end,
            )
        seen = {event.symbol for event in result.events}
        result.known = seen | (snapshot.known if snapshot else set())

        calendar_time = (
            now
            if fetched_calendar is not None
            else (calendar_sync.synced_at if calendar_sync else None)
        )
        result.calendar_available = (not needs_calendar) or calendar_time is not None
        times: list[datetime] = []
        if needs_calendar and calendar_time is not None:
            times.append(calendar_time)
        for root in roots:
            if not needs_history:
                result.history[root] = "not_requested"
                continue
            sync = snapshot.syncs.get(root) if snapshot else None
            if root in fetched_history or root in result.not_found:
                result.history[root] = "complete"
                times.append(now)
            elif sync is not None and sync.synced_at is not None:
                result.history[root] = "complete"
                times.append(sync.synced_at)
            else:
                result.history[root] = "pending"
        meta = response_meta.current()
        for moment in times:
            meta.record_fetch(moment)

        if snapshot is not None:
            failure = result.calendar_error if result.calendar_available else None
            code = failure.code if failure else None
            if (
                code is None
                and needs_calendar
                and not plan.calendar_due
                and calendar_sync is not None
                and calendar_sync.failed_at is not None
                and calendar_due(
                    now=now,
                    today=today,
                    request_end=read_end,
                    calendar=calendar_sync,
                    resync=timedelta(hours=settings.EARNINGS_CALENDAR_RESYNC_HOURS),
                    retry=timedelta(0),
                )
            ):
                # A refresh is overdue but paused after a failure: data is stale.
                code = "PROVIDER_ERROR"
            for root, failure in result.errors.items():
                if root in seen:
                    code = code or failure.code
            if code:
                meta.mark_stale(code)
        return result

    # --------------------------------------------- per-symbol providers (D2-D4)

    async def _load_symbol_state(
        self,
        name: str,
        roots: list[str],
        days: list[date],
        span: tuple[date, date],
        use_store: bool,
    ) -> _SymState:
        if use_store:
            async def load() -> _SymState:
                async with engine.session_scope(operation="read") as session:
                    events = await repo.read_events(session, name, roots, *span)
                    syncs = await repo.get_syncs(
                        session, name, [*roots, *(repo.day_scope(d) for d in days)]
                    )
                    known = await repo.known_symbols(session, name, roots)
                day_syncs = {}
                for day in days:
                    info = _sync_info(syncs.get(repo.day_scope(day)))
                    if info is not None:
                        day_syncs[day] = info
                return _SymState(
                    True, events, day_syncs,
                    {r: info for r in roots if (info := _sync_info(syncs.get(r)))},
                    known,
                )

            state = await engine.guarded(load, None)
            if state is not None:
                return state
        return await self._load_ephemeral(name, roots, days)

    async def _load_ephemeral(self, name: str, roots: list[str], days: list[date]) -> _SymState:
        state = _SymState(False)
        redis = budget_redis()
        if redis is None:
            return state

        async def read(key: str) -> tuple[list[EarningsEvent], datetime] | None:
            try:
                async with telemetry_span("redis", "read"):
                    raw = await redis.get(key)
                if not raw:
                    return None
                payload = json.loads(raw)
                return (
                    [EarningsEvent.model_validate(item) for item in payload["events"]],
                    datetime.fromisoformat(payload["fetched_at"]),
                )
            except Exception:
                logger.debug("Earnings cache unavailable", exc_info=True)
                return None

        for day in days:
            hit = await read(DAY_KEY.format(provider=name, day=day.isoformat()))
            if hit:
                state.eph_days[day] = hit[0]
                state.day_syncs[day] = SyncInfo(synced_at=hit[1])
        for root in roots:
            hit = await read(SYMBOL_KEY.format(provider=name, root=root))
            if hit:
                state.eph_symbols[root] = hit[0]
                state.symbol_syncs[root] = SyncInfo(synced_at=hit[1])
        return state

    async def _cache_ephemeral(
        self, key: str, events: list[EarningsEvent], fetched_at: datetime, ttl: int
    ) -> None:
        redis = budget_redis()
        if redis is None:
            return
        try:
            payload = {
                "fetched_at": fetched_at.isoformat(),
                "events": [event.model_dump(mode="json") for event in events],
            }
            async with telemetry_span("redis-write", "write"):
                await redis.set(key, json.dumps(payload), ex=ttl)
        except Exception:
            logger.debug("Earnings cache write failed", exc_info=True)

    @staticmethod
    def _symbol_inputs(
        roots: list[str], state: _SymState, today: date, window_end: date
    ) -> list[SymbolInput]:
        events = state.events
        if not state.store:
            events = merge_ephemeral(state.eph_days, state.eph_symbols, today)
        actuals_from = today - timedelta(days=settings.EARNINGS_ACTUALS_WINDOW_DAYS)
        by_root: dict[str, list[EarningsEvent]] = defaultdict(list)
        for event in events:
            by_root[event.symbol].append(event)
        inputs = []
        for root in roots:
            mine = by_root.get(root, [])
            inputs.append(
                SymbolInput(
                    root,
                    state.symbol_syncs.get(root),
                    latest_event=max((e.report_date for e in mine), default=None),
                    has_upcoming=any(e.report_date >= today for e in mine),
                    in_window=any(
                        today <= e.report_date <= window_end
                        and e.report_date in state.day_syncs
                        for e in mine
                    ),
                    unreported_recent=any(
                        e.eps_actual is None and actuals_from <= e.report_date <= today
                        for e in mine
                    ),
                )
            )
        return inputs

    async def _gather_symbol_mode(
        self,
        provider: BaseEarningsProvider,
        roots: list[str],
        start: date,
        end: date,
        fetch_history: bool,
        fetch_upcoming: bool,
        read_start: date,
        read_end: date,
    ) -> _Gathered:
        assert isinstance(provider, BaseEarningsUpcomingProvider)
        name = provider.name
        today = earnings_today()
        now = datetime.now(UTC)
        days = window_days(today, settings.EARNINGS_DAY_CALENDAR_WEEKDAYS)
        has_days = provider.earnings_day_calendar
        needs_window = has_days and fetch_upcoming and read_end >= days[0]
        needs_next = fetch_upcoming and read_end >= today
        needs_past = fetch_history and start < today
        retry = timedelta(minutes=settings.EARNINGS_RETRY_MINUTES)
        span = (
            min(read_start, today - timedelta(days=PLANNER_SPAN_DAYS)),
            max(read_end, today + timedelta(days=PLANNER_SPAN_DAYS)),
        )
        state = await self._load_symbol_state(name, roots, days, span, True)
        initial_state = state
        store = state.store
        budget = getattr(provider, "budget", None)
        result = _Gathered([], {}, set())
        wrote = False
        quota_hit = False
        pending_days: tuple[date, ...] = ()
        paused_days: tuple[date, ...] = ()
        fetched_days: dict[date, list[EarningsEvent]] = {}
        fetched_symbols: dict[str, list[EarningsEvent]] = {}

        if needs_window:
            remaining = await budget.remaining() if budget is not None else None
            plan = plan_days(
                now=now, today=today, weekdays=settings.EARNINGS_DAY_CALENDAR_WEEKDAYS,
                syncs=state.day_syncs, retry=retry, budget_remaining=remaining,
            )
            pending_days, paused_days = plan.pending, plan.paused
            for day in plan.due:
                try:
                    events = await provider.get_earnings_for_date(day)
                except AppError as exc:
                    result.calendar_error = result.calendar_error or exc
                    if exc.code == "PROVIDER_QUOTA_EXHAUSTED":
                        quota_hit = True
                        break
                    if store:
                        await self._store_call(
                            lambda s, d=day: repo.mark_failed(s, name, repo.day_scope(d), now)  # type: ignore[misc]
                        )
                    continue
                fetched_days[day] = events
                if store:
                    wrote |= await self._store_call(
                        lambda s, d=day, e=events: repo.replace_day(s, name, d, e, today, now)  # type: ignore[misc]
                    )
                else:
                    await self._cache_ephemeral(
                        DAY_KEY.format(provider=name, day=day.isoformat()), events, now, DAY_KEY_TTL
                    )
                    state.eph_days[day] = events
                state.day_syncs[day] = SyncInfo(synced_at=now)
            if store and wrote:
                state = await self._load_symbol_state(name, roots, days, span, True)
                store = state.store

        symbol_plan = None
        if needs_next or needs_past:
            # After the provider signalled an exhausted quota during the window, no
            # slot is left: due symbols become pending with the budget message.
            if quota_hit:
                remaining = 0
            else:
                remaining = await budget.remaining() if budget is not None else None
            symbol_plan = plan_symbols(
                now=now,
                symbols=self._symbol_inputs(roots, state, today, days[-1]),
                needs_past=needs_past, needs_next=needs_next,
                # Actuals come from the day calendar only when this request uses it.
                has_day_calendar=needs_window,
                resync=timedelta(days=settings.EARNINGS_SYMBOL_RESYNC_DAYS),
                retry=retry, budget_remaining=remaining,
            )
            attempted: list[str] = []
            for root in symbol_plan.due:
                attempted.append(root)
                try:
                    events = await provider.get_symbol_earnings(root)
                except DataNotFoundError:
                    events = []
                    result.not_found.add(root)
                except AppError as exc:
                    result.errors[root] = exc
                    if exc.code == "PROVIDER_QUOTA_EXHAUSTED":
                        quota_hit = True
                        result.pending_reason[root] = "provider request budget exhausted"
                        break
                    if store:
                        await self._store_call(lambda s, r=root: repo.mark_failed(s, name, r, now))  # type: ignore[misc]
                    continue
                fetched_symbols[root] = events
                if store:
                    wrote |= await self._store_call(
                        lambda s, r=root, e=events: repo.upsert_history(  # type: ignore[misc]
                            s, name, r, e, now, prune_upcoming_from=today
                        )
                    )
                else:
                    await self._cache_ephemeral(
                        SYMBOL_KEY.format(provider=name, root=root), events, now,
                        settings.EARNINGS_SYMBOL_RESYNC_DAYS * 86400,
                    )
                    state.eph_symbols[root] = events
                state.symbol_syncs[root] = SyncInfo(synced_at=now)
            skipped = [
                *(r for r in symbol_plan.due if quota_hit and r not in attempted),
                *symbol_plan.pending,
            ]
            if skipped:
                quota = await self._quota_error(provider)
                for root in skipped:
                    result.pending_reason[root] = "provider request budget exhausted"
                    result.budget_errors[root] = quota

        # ---- compose
        if store and wrote:
            stored = await self._read_events(name, roots, read_start, read_end)
            events = stored if stored is not None else state.events
        elif store:
            events = state.events
        else:
            events = merge_ephemeral(state.eph_days, state.eph_symbols, today)
        selected = set(roots)
        result.events = reconcile_events(
            [e for e in events if e.symbol in selected and read_start <= e.report_date <= read_end]
        )
        result.used_store = initial_state.store
        result.from_provider = bool(fetched_days or fetched_symbols)
        result.from_redis = not initial_state.store and bool(
            (needs_window and initial_state.eph_days) or initial_state.eph_symbols
        )
        if initial_state.store and current_telemetry() is not None:
            result.from_store = not result.from_provider or _kept_stored_event(
                initial_state.events, result.events,
                [e for batch in (*fetched_days.values(), *fetched_symbols.values()) for e in batch],
                read_start, read_end,
            )
        seen = {event.symbol for event in result.events}
        result.known = seen | state.known | set(state.symbol_syncs)
        result.calendar_available = not (result.calendar_error and not result.events)

        meta = response_meta.current()
        if needs_window:
            for day in days:
                info = state.day_syncs.get(day)
                if info is not None and info.synced_at is not None:
                    meta.record_fetch(info.synced_at)
        for item in self._symbol_inputs(roots, state, today, days[-1]):
            if item.sync is not None and item.sync.synced_at is not None and not (needs_window and item.in_window):
                meta.record_fetch(item.sync.synced_at)
        for root in roots:
            if not needs_past:
                result.history[root] = "not_requested"
            elif root in state.symbol_syncs or root in fetched_symbols or root in result.not_found:
                result.history[root] = "complete"
            else:
                result.history[root] = "pending"

        if store:
            code = None
            if pending_days or any(r in result.budget_errors for r in seen):
                code = "PROVIDER_QUOTA_EXHAUSTED"
            elif result.calendar_error is not None and result.events:
                code = result.calendar_error.code
            elif paused_days:
                code = "PROVIDER_ERROR"
            for root, failure in result.errors.items():
                if root in seen:
                    code = code or failure.code
            if code:
                meta.mark_stale(code)
        return result

    async def _compose(
        self,
        provider: str,
        roots: list[str],
        read_start: date,
        read_end: date,
        snapshot: _Snapshot | None,
        cached: tuple[list[EarningsEvent], datetime] | None,
        fetched_calendar: list[EarningsEvent] | None,
        fetched_history: dict[str, list[EarningsEvent]],
        wrote: bool,
    ) -> list[EarningsEvent]:
        selected = set(roots)
        history = [event for events in fetched_history.values() for event in events]
        if snapshot is not None:
            if wrote:
                stored = await self._read_events(provider, roots, read_start, read_end)
                if stored is not None:
                    return stored
                # The store failed after the provider answered: merge in memory.
                return [*snapshot.events, *(fetched_calendar or []), *history]
            return snapshot.events
        calendar = fetched_calendar if fetched_calendar is not None else (
            cached[0] if cached else []
        )
        return [event for event in calendar if event.symbol in selected] + history

    # ----------------------------------------------------------------- public

    async def _open_roles(
        self, stack: AsyncExitStack, provider_name: str | None, kind: str
    ) -> _Roles:
        """Resolve the providers serving the requested roles (design D10)."""
        registry = self.registry
        need_up = kind in ("all", "upcoming")
        need_hist = kind in ("all", "reported")
        if provider_name is not None:
            provider = await stack.enter_async_context(
                registry.use_earnings_provider(provider_name)
            )
            has_up = isinstance(provider, BaseEarningsUpcomingProvider)
            has_hist = isinstance(provider, BaseEarningsHistoryProvider)
            if kind == "upcoming" and not has_up or kind == "reported" and not has_hist:
                role = "upcoming" if kind == "upcoming" else "history"
                available = registry.list_available_providers()[f"earnings_{role}"]
                text = (
                    f"Provider '{provider.name}' only delivers reported earnings."
                    if role == "upcoming"
                    else f"Provider '{provider.name}' only delivers upcoming earnings."
                )
                error = CapabilityNotSupportedError(
                    provider.name, "upcoming earnings" if role == "upcoming" else "reported earnings",
                    sec_type="stock", supported=available,
                )
                error.message = f"{text} Providers with {role} earnings: {', '.join(available) or 'none'}."
                raise error
            return _Roles(provider if has_up else None, provider if has_hist else None, {})
        up_name = registry.default_earnings_upcoming_provider if need_up else None
        hist_name = registry.default_earnings_history_provider if need_hist else None
        if up_name is None and hist_name is None:
            if (
                registry.default_earnings_upcoming_provider is None
                and registry.default_earnings_history_provider is None
            ):
                raise AppError(
                    "No earnings provider configured — enable a provider in the admin UI",
                    "PROVIDER_NOT_AVAILABLE",
                )
            role = "upcoming" if need_up else "history"
            raise AppError(
                f"No {role} earnings provider configured — enable a provider in the admin UI",
                "PROVIDER_NOT_AVAILABLE",
            )
        missing = {
            role: f"no {role} earnings provider configured"
            for role, needed, name in (
                ("upcoming", need_up, up_name),
                ("history", need_hist, hist_name),
            )
            if needed and name is None
        }
        up: BaseEarningsProvider | None = None
        hist: BaseEarningsProvider | None = None
        if up_name is not None:
            up = await stack.enter_async_context(registry.use_earnings_provider(up_name, "upcoming"))
        if hist_name is not None:
            if hist_name == up_name:
                hist = up
            else:
                hist = await stack.enter_async_context(
                    registry.use_earnings_provider(hist_name, "history")
                )
        return _Roles(up, hist, missing)

    @staticmethod
    def _compose_events(
        up_events: list[EarningsEvent], hist_events: list[EarningsEvent]
    ) -> list[EarningsEvent]:
        reported = [e for e in hist_events if e.reported]
        keep = []
        for event in up_events:
            if event.reported:
                continue
            if any(
                r.symbol == event.symbol and abs((r.report_date - event.report_date).days) <= 7
                for r in reported
            ):
                continue
            keep.append(event)
        return sorted([*reported, *keep], key=lambda e: (e.report_date, e.symbol))

    @staticmethod
    def _merge_statuses(
        up: list[EarningsSymbolStatus] | None,
        hist: list[EarningsSymbolStatus] | None,
        missing: dict[str, str],
        symbols: list[ParsedSymbol],
    ) -> list[EarningsSymbolStatus]:
        base = hist or up or []
        if up is None or hist is None:
            result = list(base)
        else:
            result = []
            for u, h in zip(up, hist, strict=True):
                if h.status == "not_applicable":
                    result.append(h)
                    continue
                if "ok" in (u.status, h.status):
                    status, message = "ok", h.message if h.status == "ok" else u.message
                elif "error" in (u.status, h.status):
                    failed = u if u.status == "error" else h
                    status, message = "error", failed.message
                else:
                    status, message = "not_found", h.message or u.message
                result.append(
                    EarningsSymbolStatus(
                        symbol=h.symbol, status=status, history=h.history, message=message  # type: ignore[arg-type]
                    )
                )
        if missing:
            note = "; ".join(missing.values())
            result = [
                s if s.status == "not_applicable" or s.message
                else s.model_copy(update={"message": note})
                for s in result
            ]
        return result

    async def _serve(
        self,
        symbols: list[ParsedSymbol],
        start: date,
        end: date,
        provider_name: str | None,
        kind: str,
        single: bool = False,
    ) -> EarningsResult:
        today = earnings_today()
        roots = [s.root for s in symbols if not is_etf(s)]
        async with AsyncExitStack() as stack:
            roles = await self._open_roles(stack, provider_name, kind)
            up, hist = roles.upcoming, roles.history
            if up is not None and hist is not None and up.name == hist.name:
                provider = up
                bind_data_provider(provider.name)
                gathered = await self._gather(
                    provider, roots, start, end,
                    fetch_history=kind != "upcoming", fetch_upcoming=kind != "reported",
                    read_start=start, read_end=end,
                )
                _record_sources(gathered)
                events = [e for e in gathered.events if start <= e.report_date <= end]
                statuses = self._statuses(symbols, gathered, provider, start)
                composed = None
                name: str | None = provider.name
            else:
                composed = {}
                if up is not None:
                    composed["upcoming"] = up.name
                if hist is not None:
                    composed["history"] = hist.name
                bind_data_provider(*composed.values())
                up_g = hist_g = None
                if up is not None:
                    up_g = await self._gather(
                        up, roots, start, end, fetch_history=False,
                        read_start=start, read_end=end,
                    )
                if hist is not None:
                    hist_g = await self._gather(
                        hist, roots, start, end, fetch_history=True, fetch_upcoming=False,
                        read_start=start, read_end=end,
                    )
                _record_sources(up_g, hist_g)
                in_range = lambda g: [e for e in (g.events if g else []) if start <= e.report_date <= end]
                events = self._compose_events(in_range(up_g), in_range(hist_g))
                statuses = self._merge_statuses(
                    self._statuses(symbols, up_g, up, start) if up_g and up else None,
                    self._statuses(symbols, hist_g, hist, start) if hist_g and hist else None,
                    roles.missing, symbols,
                )
                gathered = hist_g or up_g  # type: ignore[assignment]
                provider = hist or up  # type: ignore[assignment]
                if len(composed) == 1:
                    name, composed = next(iter(composed.values())), None
                else:
                    name = None
            if kind == "upcoming":
                events = [e for e in events if not e.reported and e.report_date >= today]
            elif kind == "reported":
                events = [e for e in events if e.reported]
            applicable = [s for s in statuses if s.status != "not_applicable"]
            if single and not events and gathered is not None:
                root = symbols[0].root
                if root in gathered.errors:
                    raise gathered.errors[root]
                if root in gathered.budget_errors:
                    raise gathered.budget_errors[root]
                if statuses[0].status == "error":
                    raise self._first_error(gathered)
                if root not in gathered.known:
                    raise DataNotFoundError("Earnings", symbols[0].canonical)
            if applicable and not events and all(s.status == "error" for s in applicable):
                raise self._first_error(gathered)
            return EarningsResult(name, events, statuses, composed)

    async def calendar(
        self,
        symbols: list[ParsedSymbol],
        start: date,
        end: date,
        provider_name: str | None = None,
        kind: str = "all",
    ) -> EarningsResult:
        if start > end:
            raise DataValidationError("from must not be after to")
        if (end - start).days > MAX_RANGE_DAYS:
            raise DataValidationError(f"The range must not exceed {MAX_RANGE_DAYS} days")
        return await self._serve(symbols, start, end, provider_name, kind)

    def _first_error(self, gathered: _Gathered) -> AppError:
        error = gathered.calendar_error or next(iter(gathered.errors.values()), None)
        return error or next(iter(gathered.budget_errors.values()))

    def _statuses(
        self,
        symbols: list[ParsedSymbol],
        gathered: _Gathered,
        provider: BaseEarningsProvider,
        start: date,
    ) -> list[EarningsSymbolStatus]:
        have = {event.symbol for event in gathered.events}
        calendar_down = (
            gathered.calendar_error is not None and not gathered.calendar_available
        )
        statuses = []
        for symbol in symbols:
            if is_etf(symbol):
                statuses.append(
                    EarningsSymbolStatus(
                        symbol=symbol.canonical,
                        status="not_applicable",
                        message="Earnings are not available for ETFs",
                    )
                )
                continue
            root = symbol.root
            error = gathered.errors.get(root)
            if root in gathered.pending_reason:
                error = None
            history = gathered.history.get(root, "not_requested")
            message = gathered.pending_reason.get(root)
            if error is not None and root not in have:
                status, message = "error", error.message
            elif calendar_down and root not in have:
                status, message = "error", gathered.calendar_error.message  # type: ignore[union-attr]
            elif root not in have and (
                root in gathered.not_found
                or (history == "complete" and root not in gathered.known)
            ):
                status = "not_found"
            else:
                status = "ok"
                if calendar_down:
                    message = f"Upcoming calendar unavailable ({gathered.calendar_error.code})"  # type: ignore[union-attr]
            statuses.append(
                EarningsSymbolStatus(
                    symbol=symbol.canonical, status=status, history=history, message=message  # type: ignore[arg-type]
                )
            )
        return statuses

    async def company(
        self,
        symbol: ParsedSymbol,
        start: date,
        end: date,
        provider_name: str | None = None,
        kind: str = "all",
    ) -> EarningsResult:
        if start > end:
            raise DataValidationError("from must not be after to")
        if is_etf(symbol):
            name = provider_name or self.registry.default_earnings_history_provider or (
                self.registry.default_earnings_upcoming_provider or "earnings"
            )
            error = CapabilityNotSupportedError(
                name, "earnings", sec_type="etf", supported=["stock"]
            )
            error.details["http_status"] = 422
            raise error
        return await self._serve([symbol], start, end, provider_name, kind, single=True)

    async def _stored_last_reported(
        self, name: str, roots: list[str], today: date
    ) -> dict[str, EarningsEvent]:
        async def load() -> list[EarningsEvent]:
            async with engine.session_scope(operation="read") as session:
                return await repo.read_events(
                    session, name, roots, today - timedelta(days=HISTORY_LOOKBACK_DAYS), today
                )

        events = await engine.guarded(load, None) or []
        latest: dict[str, EarningsEvent] = {}
        for event in events:
            if event.reported and (
                event.symbol not in latest or event.report_date > latest[event.symbol].report_date
            ):
                latest[event.symbol] = event
        return latest

    async def next(
        self, symbols: list[ParsedSymbol], provider_name: str | None = None
    ) -> NextResult:
        today = earnings_today()
        roots = [s.root for s in symbols if not is_etf(s)]
        async with AsyncExitStack() as stack:
            roles = await self._open_roles(stack, provider_name, "upcoming")
            provider = roles.upcoming
            assert provider is not None
            bind_data_provider(provider.name)
            gathered = await self._gather(
                provider, roots, today, today + timedelta(days=CALENDAR_HORIZON_DAYS),
                fetch_history=False,
                read_start=today - timedelta(days=HISTORY_LOOKBACK_DAYS),
                read_end=today + timedelta(days=CALENDAR_HORIZON_DAYS),
            )
            if roots and not gathered.calendar_available and gathered.calendar_error:
                raise gathered.calendar_error
            history_events: dict[str, EarningsEvent] = {}
            hist_default = self.registry.default_earnings_history_provider
            if provider_name is None and hist_default and hist_default != provider.name:
                history_events = await self._stored_last_reported(hist_default, roots, today)
            _record_sources(gathered, stored_report=bool(history_events))
            by_symbol: dict[str, list[EarningsEvent]] = defaultdict(list)
            for event in gathered.events:
                by_symbol[event.symbol].append(event)
            rows = []
            for symbol in symbols:
                if is_etf(symbol):
                    rows.append(
                        NextEarnings(
                            symbol=symbol.canonical,
                            status="not_applicable",
                            message="Earnings are not available for ETFs",
                        )
                    )
                    continue
                events = by_symbol.get(symbol.root, [])
                upcoming = min(
                    (e for e in events if e.report_date >= today),
                    key=lambda e: e.report_date,
                    default=None,
                )
                reported = history_events.get(symbol.root) or max(
                    (e for e in events if e.reported and e is not upcoming),
                    key=lambda e: e.report_date,
                    default=None,
                )
                failure = None
                if upcoming is None and not events:
                    failure = gathered.errors.get(symbol.root) or gathered.budget_errors.get(symbol.root)
                if failure is not None:
                    message = gathered.pending_reason.get(symbol.root) or failure.message
                    rows.append(
                        NextEarnings(
                            symbol=symbol.canonical, status="error", message=message,
                            last_reported=reported,
                        )
                    )
                    continue
                rows.append(
                    NextEarnings(
                        symbol=symbol.canonical,
                        event=upcoming,
                        days_until=(upcoming.report_date - today).days if upcoming else None,
                        last_reported=reported,
                        status="ok" if upcoming else "none_scheduled",
                        message=None
                        if upcoming
                        else "No announced date in the provider's calendar",
                    )
                )
            return NextResult(provider.name, rows)


earnings_service = EarningsService()
