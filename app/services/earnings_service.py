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
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app import response_meta
from app.config import settings
from app.models.earnings import (
    EarningsEvent,
    EarningsSymbolStatus,
    NextEarnings,
    earnings_today,
)
from app.providers.base import BaseEarningsProvider
from app.providers.registry import ProviderRegistry, get_registry
from app.providers.request_budget import budget_redis
from app.services.earnings_planner import (
    CALENDAR_HORIZON_DAYS,
    HistoryInput,
    SyncInfo,
    calendar_due,
    plan_refresh,
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
from app.utils.symbols import ParsedSymbol, parse_symbol

logger = logging.getLogger(__name__)

MAX_SYMBOLS = 50
MAX_RANGE_DAYS = 800
HISTORY_LOOKBACK_DAYS = 1095
EARNINGS_TYPES = frozenset({"stock", "etf"})
CALENDAR_KEY = "mdh:earnings:provider-calendar:{provider}:12month"

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
        result.append(max(pool, key=lambda e: (e.updated_at, e.report_date)))
    return sorted(result, key=lambda e: (e.report_date, e.symbol))


@dataclass
class EarningsResult:
    provider: str
    events: list[EarningsEvent]
    symbols: list[EarningsSymbolStatus]


@dataclass
class NextResult:
    provider: str
    rows: list[NextEarnings]


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


def _sync_info(state: repo.SyncState | None) -> SyncInfo | None:
    if state is None:
        return None
    return SyncInfo(state.synced_at, state.sync_failed_at, state.covered_to)


class EarningsService:
    def __init__(self, registry: ProviderRegistry | None = None) -> None:
        self.registry = registry or get_registry()
        self._locks: dict[str, asyncio.Lock] = {}

    # ----------------------------------------------------------- store access

    async def _store_call(
        self, work: Callable[[AsyncSession], Awaitable[object]]
    ) -> bool:
        async def run() -> bool:
            async with engine.session_scope() as session:
                await work(session)
            return True

        return bool(await engine.guarded(run, False))

    async def _read_events(
        self, provider: str, roots: list[str], start: date, end: date
    ) -> list[EarningsEvent] | None:
        async def load() -> list[EarningsEvent]:
            async with engine.session_scope() as session:
                return await repo.read_events(session, provider, roots, start, end)

        return await engine.guarded(load, None)

    async def _read_snapshot(
        self, provider: str, roots: list[str], start: date, end: date, today: date
    ) -> _Snapshot | None:
        window_start = today - timedelta(days=settings.EARNINGS_ACTUALS_WINDOW_DAYS)

        async def load() -> _Snapshot:
            async with engine.session_scope() as session:
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
    ) -> _Gathered:
        if not roots:
            return _Gathered([], {}, set())
        lock = self._locks.setdefault(provider.name, asyncio.Lock())
        async with lock:
            return await self._gather_locked(
                provider, roots, start, end, fetch_history, read_start, read_end
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
    ) -> _Gathered:
        name = provider.name
        today = earnings_today()
        now = datetime.now(UTC)
        needs_calendar = provider.earnings_upcoming and read_end >= today
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
                fetched_calendar = await provider.get_upcoming_earnings(
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
                events = await provider.get_earnings_history(root)
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
                        lambda s, r=root: repo.mark_failed(s, name, r, now)
                    )
                continue
            fetched_history[root] = events
            if snapshot is not None:
                wrote |= await self._store_call(
                    lambda s, r=root, e=events: repo.upsert_history(s, name, r, e, now)
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
            for root, exc in result.errors.items():
                if root in seen:
                    code = code or exc.code
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

    async def calendar(
        self,
        symbols: list[ParsedSymbol],
        start: date,
        end: date,
        provider_name: str | None = None,
    ) -> EarningsResult:
        if start > end:
            raise DataValidationError("from must not be after to")
        if (end - start).days > MAX_RANGE_DAYS:
            raise DataValidationError(f"The range must not exceed {MAX_RANGE_DAYS} days")
        async with self.registry.use_earnings_provider(provider_name) as provider:
            structlog.contextvars.bind_contextvars(provider=provider.name)
            roots = [s.root for s in symbols if not is_etf(s)]
            gathered = await self._gather(
                provider, roots, start, end, fetch_history=True,
                read_start=start, read_end=end,
            )
            events = [e for e in gathered.events if start <= e.report_date <= end]
            statuses = self._statuses(symbols, gathered, provider, start)
            applicable = [s for s in statuses if s.status != "not_applicable"]
            if applicable and not events and all(s.status == "error" for s in applicable):
                raise self._first_error(gathered)
            return EarningsResult(provider.name, events, statuses)

    def _first_error(self, gathered: _Gathered) -> AppError:
        return gathered.calendar_error or next(iter(gathered.errors.values()))

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
    ) -> EarningsResult:
        if start > end:
            raise DataValidationError("from must not be after to")
        async with self.registry.use_earnings_provider(provider_name) as provider:
            structlog.contextvars.bind_contextvars(provider=provider.name)
            if is_etf(symbol):
                error = CapabilityNotSupportedError(
                    provider.name, "earnings", sec_type="etf", supported=["stock"]
                )
                error.details["http_status"] = 422
                raise error
            gathered = await self._gather(
                provider, [symbol.root], start, end, fetch_history=True,
                read_start=start, read_end=end,
            )
            events = [e for e in gathered.events if start <= e.report_date <= end]
            statuses = self._statuses([symbol], gathered, provider, start)
            if not events:
                if symbol.root in gathered.errors:
                    raise gathered.errors[symbol.root]
                if symbol.root in gathered.budget_errors:
                    raise gathered.budget_errors[symbol.root]
                if statuses[0].status == "error":
                    raise self._first_error(gathered)
                if symbol.root not in gathered.known:
                    raise DataNotFoundError("Earnings", symbol.canonical)
            return EarningsResult(provider.name, events, statuses)

    async def next(
        self, symbols: list[ParsedSymbol], provider_name: str | None = None
    ) -> NextResult:
        async with self.registry.use_earnings_provider(provider_name) as provider:
            structlog.contextvars.bind_contextvars(provider=provider.name)
            if not provider.earnings_upcoming:
                raise CapabilityNotSupportedError(
                    provider.name, "upcoming earnings", sec_type="stock", supported=[]
                )
            today = earnings_today()
            roots = [s.root for s in symbols if not is_etf(s)]
            gathered = await self._gather(
                provider, roots, today, today + timedelta(days=CALENDAR_HORIZON_DAYS),
                fetch_history=False,
                read_start=today - timedelta(days=HISTORY_LOOKBACK_DAYS),
                read_end=today + timedelta(days=CALENDAR_HORIZON_DAYS),
            )
            if roots and not gathered.calendar_available and gathered.calendar_error:
                raise gathered.calendar_error
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
                reported = max(
                    (e for e in events if e.reported and e is not upcoming),
                    key=lambda e: e.report_date,
                    default=None,
                )
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
