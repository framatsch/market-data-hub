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

"""Request-driven synchronisation of stored history (design D3-D7, D10).

`plan` is a pure function; `HistorySync` runs the plan against the database and
the provider loader supplied by the service.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Generic, Literal, TypeVar

from app.config import settings
from app.market_hours import (
    as_utc,
    bar_length_seconds,
    is_bar_closed,
    is_closed,
    last_closed_day,
    market_state,
    newest_closed_key,
)
from app.models.price import PriceBar
from app.models.volatility import VolatilityPoint
from app.observability.metrics import record_history_store_read
from app.observability.telemetry import StoreOutcome, current_telemetry
from app.store import engine, repository
from app.store.repository import Series, SeriesKey, midnight
from app.utils.errors import AppError

logger = logging.getLogger(__name__)
Item = TypeVar("Item", PriceBar, VolatilityPoint)
StepKind = Literal["full_load", "backfill", "tail_sync"]
NOT_STALE_CODES = frozenset(
    {
        "PROVIDER_NOT_ENTITLED",
        "CAPABILITY_NOT_SUPPORTED",
        "DATA_VALIDATION_ERROR",
        "DATA_NOT_FOUND",
        "INVALID_PROVIDER",
    }
)
MIN_IV_POINTS_STALE = 20


def is_transient(exc: BaseException) -> bool:
    """Provider failures that may be answered from stored data."""
    return isinstance(exc, AppError) and exc.code not in NOT_STALE_CODES


# --------------------------------------------------------------------- profile


@dataclass(frozen=True)
class Profile:
    """How a series reads its positions, closes bars and compares revisions."""

    dataset: Literal["prices", "iv"]
    interval: str
    extended_hours: bool = False

    @property
    def intraday(self) -> bool:
        return self.dataset == "prices" and self.interval in {"1h", "4h"}

    @property
    def metric_dataset(self) -> str:
        return self.dataset

    def position(self, item: Any) -> datetime:
        if self.dataset == "iv":
            return repository.iv_position(item)
        return repository.bar_position(self.interval, item)

    def signature(self, item: Any) -> tuple[Any, ...]:
        if self.dataset == "iv":
            return (item.iv_call, item.iv_put, item.iv)
        return (item.open, item.high, item.low, item.close)

    def closed(self, item: Any, now: datetime) -> bool:
        if self.dataset == "iv":
            return is_closed(item.date, now)
        return is_bar_closed(self.interval, item.start, now, self.extended_hours)

    def storable(self, item: Any) -> bool:
        return self.dataset != "iv" or repository.has_iv_value(item)

    def newest_closed(self, now: datetime) -> datetime:
        if self.dataset == "iv":
            return midnight(last_closed_day(now))
        return newest_closed_key(self.interval, now, self.extended_hours)

    def first_open(self, now: datetime) -> datetime | None:
        """Start of the first period that is not closed yet (None: there is none)."""
        if self.dataset == "iv":
            return None
        newest = self.newest_closed(now)
        if self.interval == "1d":
            day = newest + timedelta(days=1)
            while day.weekday() >= 5:
                day += timedelta(days=1)
            return day
        if self.interval == "1w":
            return newest + timedelta(days=7)
        if not self.extended_hours and market_state(now) == "settled":
            return None
        length = bar_length_seconds(self.interval) or 3600
        return newest + timedelta(seconds=length)

    def request_range(
        self, start: datetime, end: datetime
    ) -> tuple[datetime, datetime]:
        """Request bounds as coverage positions."""
        start, end = as_utc(start), as_utc(end)
        if self.intraday:
            return start, end
        first = start.date()
        if self.interval == "1w":
            first -= timedelta(days=first.weekday())
        return midnight(first), midnight(end.date())


# --------------------------------------------------------------------- planner


@dataclass(frozen=True)
class Coverage:
    covered_from: datetime | None = None
    covered_to: datetime | None = None
    synced_at: datetime | None = None
    sync_failed_at: datetime | None = None

    @property
    def last_attempt(self) -> datetime | None:
        times = [t for t in (self.synced_at, self.sync_failed_at) if t is not None]
        return max(times) if times else None

    @property
    def known(self) -> bool:
        return self.covered_from is not None and self.covered_to is not None


@dataclass(frozen=True)
class Step:
    kind: StepKind
    start: datetime
    end: datetime | None  # None = until now


def plan(
    profile: Profile,
    start: datetime,
    end: datetime,
    coverage: Coverage,
    now: datetime,
    resync_seconds: int,
    force: bool = False,
) -> list[Step]:
    """Decide which provider calls a request needs (empty: answer from the store)."""
    now = as_utc(now)
    rs, re = profile.request_range(start, end)
    attempt = coverage.last_attempt
    throttled = (
        not force
        and attempt is not None
        and (now - attempt).total_seconds() < resync_seconds
    )
    if not coverage.known:
        # Nothing stored to fall back on: always ask the provider (as without a store).
        return [Step("full_load", rs, as_utc(end))]
    assert coverage.covered_from is not None and coverage.covered_to is not None
    steps: list[Step] = []
    if rs < coverage.covered_from and not (profile.intraday and throttled):
        pad = timedelta(days=1) if not profile.intraday else timedelta()
        steps.append(Step("backfill", rs, coverage.covered_from + pad))
    newest = profile.newest_closed(now)
    first_open = profile.first_open(now)
    due = coverage.covered_to < newest or (first_open is not None and re >= first_open)
    if due and not throttled:
        steps.append(Step("tail_sync", coverage.covered_to, None))
    return steps


def label_of(steps: Sequence[Step]) -> str:
    kinds = {step.kind for step in steps}
    for kind in ("full_load", "backfill", "tail_sync"):
        if kind in kinds:
            return kind
    return "store"


# --------------------------------------------------------------------- results


@dataclass
class Loaded(Generic[Item]):
    items: list[Item]
    source_instrument: str | None = None
    sec_type: str | None = None


Loader = Callable[[datetime, datetime], Awaitable[Loaded[Item]]]


@dataclass
class Served(Generic[Item]):
    items: list[Item]
    data_as_of: datetime | None
    result: str
    stale: bool = False
    stale_reason: str | None = None
    source_provider: str | None = None
    series: Series | None = None


class _Uncovered(Exception):
    pass


@dataclass
class _Runtime:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    forming: list[Any] = field(default_factory=list)
    last_error: str | None = None


class HistorySync:
    """Serves one dataset kind through the store; one in-process lock per series."""

    def __init__(self) -> None:
        self._runtime: dict[SeriesKey, _Runtime] = {}

    def _state(self, key: SeriesKey) -> _Runtime:
        return self._runtime.setdefault(key, _Runtime())

    async def serve(
        self,
        key: SeriesKey,
        profile: Profile,
        start: datetime,
        end: datetime,
        loader: Loader[Any],
        *,
        force: bool = False,
        now: datetime | None = None,
        sec_type: str | None = None,
        source_interval: str | None = None,
    ) -> Served[Any] | None:
        """Answer from the store; None means the store is unusable (fail-open)."""
        if engine.store_state() == "unavailable":
            await engine.probe_store()
        if not engine.store_usable():
            return None
        runtime = self._state(key)
        async with runtime.lock:
            try:
                served = await self._serve_locked(
                    key,
                    profile,
                    start,
                    end,
                    loader,
                    force,
                    now,
                    sec_type,
                    runtime,
                    source_interval,
                )
            except (AppError, asyncio.CancelledError):
                raise
            except Exception as exc:
                engine.failed(exc)
                return None
        engine.recovered()
        return served

    # ------------------------------------------------------------------ core

    async def _serve_locked(
        self,
        key: SeriesKey,
        profile: Profile,
        start: datetime,
        end: datetime,
        loader: Loader[Any],
        force: bool,
        now_override: datetime | None,
        sec_type: str | None,
        runtime: _Runtime,
        source_interval: str | None = None,
    ) -> Served[Any]:
        now = as_utc(now_override or datetime.now(UTC))
        rs, re = profile.request_range(start, end)
        async with engine.session_scope(operation="write") as session:
            series = await repository.get_or_create_series(
                session, key, sec_type, source_interval
            )
        reloaded_for_source = False
        if series.source_interval != source_interval:
            changed = True
            if series.covered_from is not None and series.covered_to is not None:
                # The bars are now produced from another source: boundaries may differ.
                try:
                    reloaded_for_source = await self._reload(
                        key, profile, series, loader, now, runtime, source_interval
                    )
                except Exception as exc:
                    if not is_transient(exc):
                        raise
                    changed = False  # retry on the next request
            if changed:
                async with engine.session_scope(operation="write") as session:
                    await repository.update_series(
                        session, series.id, source_interval=source_interval
                    )
                    series = await repository.get_series(session, key) or series
        coverage = Coverage(
            series.covered_from,
            series.covered_to,
            series.synced_at,
            series.sync_failed_at,
        )
        steps = plan(
            profile,
            start,
            end,
            coverage,
            now,
            settings.HISTORY_STORE_RESYNC_SECONDS,
            force,
        )
        result = "reload" if reloaded_for_source else label_of(steps)
        stale_reason: str | None = None
        try:
            for step in steps:
                reloaded = await self._run_step(
                    step, key, profile, series, loader, now, runtime, sec_type
                )
                if reloaded:
                    result = "reload"
                async with engine.session_scope(operation="read") as session:
                    series = await repository.get_series(session, key) or series
        except Exception as exc:
            if not is_transient(exc):
                raise
            stale_reason = getattr(exc, "code", "PROVIDER_ERROR")
            runtime.last_error = stale_reason
            async with engine.session_scope(operation="write") as session:
                await repository.update_series(session, series.id, sync_failed_at=now)
                series = await repository.get_series(session, key) or series
            if not self._covers(profile, series, rs):
                raise
            result = "stale"
        else:
            if steps:
                runtime.last_error = None
        if stale_reason is None and runtime.last_error:
            # A failed attempt inside the tail interval keeps answering from the
            # store without retrying; the answer is still marked stale.
            failed_at = series.sync_failed_at
            if (
                failed_at is not None
                and (series.synced_at is None or failed_at > series.synced_at)
                and self._covers(profile, series, rs)
                and not steps
            ):
                stale_reason = runtime.last_error
                result = "stale"
        async with engine.session_scope(operation="read") as session:
            items = await self._read(session, profile, series, rs, re, start, end)
        if stale_reason is None:
            items = self._with_forming(profile, items, runtime, rs, re, now)
        record_history_store_read(profile.metric_dataset, result)
        if (telemetry := current_telemetry()) is not None:
            outcomes: dict[str, StoreOutcome] = {
                "store": "hit",
                "tail_sync": "partial",
                "backfill": "partial",
                "full_load": "miss",
                "reload": "miss",
                "stale": "stale",
            }
            telemetry.store_outcome = outcomes.get(result)
            telemetry.data_provider = key.provider
        return Served(
            items=items,
            data_as_of=series.synced_at,
            result=result,
            stale=stale_reason is not None,
            stale_reason=stale_reason,
            series=series,
        )

    @staticmethod
    def _covers(profile: Profile, series: Series, rs: datetime) -> bool:
        if series.covered_from is None or series.covered_to is None:
            return False
        return profile.intraday or series.covered_from <= rs

    @staticmethod
    async def _read(
        session: Any,
        profile: Profile,
        series: Series,
        rs: datetime,
        re: datetime,
        start: datetime,
        end: datetime,
    ) -> list[Any]:
        if profile.dataset == "iv":
            return await repository.read_points(session, series, rs, re)
        if profile.intraday:
            return await repository.read_bars(
                session, series, as_utc(start), as_utc(end)
            )
        return await repository.read_bars(session, series, rs, re)

    @staticmethod
    def _with_forming(
        profile: Profile,
        items: list[Any],
        runtime: _Runtime,
        rs: datetime,
        re: datetime,
        now: datetime,
    ) -> list[Any]:
        known = {profile.position(item) for item in items}
        extra = [
            item
            for item in runtime.forming
            if rs <= profile.position(item) <= re
            and profile.position(item) not in known
            and not profile.closed(item, now)
        ]
        return sorted([*items, *extra], key=profile.position) if extra else items

    # ------------------------------------------------------------- one step

    async def _run_step(
        self,
        step: Step,
        key: SeriesKey,
        profile: Profile,
        series: Series,
        loader: Loader[Any],
        now: datetime,
        runtime: _Runtime,
        sec_type: str | None,
    ) -> bool:
        """Run one provider step; returns True when the series was reloaded."""
        if step.kind == "tail_sync":
            return await self._tail(key, profile, series, loader, now, runtime)
        end = step.end or now
        loaded = await loader(step.start, end)
        closed, forming = self._split(profile, loaded.items, now)
        if step.kind == "full_load":
            runtime.forming = forming
        position_end = min(
            profile.newest_closed(now), profile.request_range(step.start, end)[1]
        )
        async with engine.session_scope(operation="write") as session:
            await self._write(session, profile, series, closed, replace=False)
            fields: dict[str, Any] = {"synced_at": now, "sync_failed_at": None}
            if loaded.source_instrument:
                fields["source_instrument"] = loaded.source_instrument
            if sec_type and not series.sec_type:
                fields["sec_type"] = sec_type
            positions = sorted(profile.position(item) for item in closed)
            if step.kind == "full_load":
                fields["covered_from"] = (
                    positions[0] if profile.intraday and positions else step.start
                )
                fields["covered_to"] = self._covered_to(
                    profile, positions, position_end, None
                )
            else:
                assert series.covered_from is not None
                fields["covered_from"] = (
                    min(series.covered_from, positions[0])
                    if profile.intraday and positions
                    else (series.covered_from if profile.intraday else step.start)
                )
            await repository.update_series(session, series.id, **fields)
        return False

    @staticmethod
    def _covered_to(
        profile: Profile,
        positions: list[datetime],
        newest: datetime,
        current: datetime | None,
    ) -> datetime:
        if profile.dataset == "iv":
            candidates = [p for p in positions if p <= newest]
            base = max(candidates) if candidates else (current or newest)
            return max(base, current) if current else base
        return max(newest, current) if current else newest

    @staticmethod
    def _split(
        profile: Profile, items: list[Any], now: datetime
    ) -> tuple[list[Any], list[Any]]:
        closed: list[Any] = []
        forming: list[Any] = []
        for item in items:
            if profile.closed(item, now):
                if profile.storable(item):
                    closed.append(item)
            else:
                forming.append(item)
        return closed, forming

    @staticmethod
    async def _write(
        session: Any,
        profile: Profile,
        series: Series,
        items: list[Any],
        *,
        replace: bool,
    ) -> None:
        fn: Any
        if profile.dataset == "iv":
            fn = repository.replace_points if replace else repository.upsert_points
        else:
            fn = repository.replace_bars if replace else repository.upsert_bars
        await fn(session, series.id, items)

    async def _tail(
        self,
        key: SeriesKey,
        profile: Profile,
        series: Series,
        loader: Loader[Any],
        now: datetime,
        runtime: _Runtime,
    ) -> bool:
        overlap = settings.HISTORY_STORE_OVERLAP_BARS
        async with engine.session_scope(operation="read") as session:
            stored: list[Any]
            if profile.dataset == "iv":
                stored = await repository.newest_points(session, series, overlap)
            else:
                stored = await repository.newest_bars(session, series, overlap)
        assert series.covered_to is not None
        tail_start = (
            min(profile.position(item) for item in stored)
            if stored
            else series.covered_to
        )
        loaded = await loader(tail_start, now)
        closed, forming = self._split(profile, loaded.items, now)
        runtime.forming = forming
        by_position = {profile.position(item): item for item in loaded.items}
        newest_stored = max((profile.position(i) for i in stored), default=None)
        revised = False
        for item in stored:
            position = profile.position(item)
            fresh = by_position.get(position)
            if fresh is None or profile.signature(fresh) == profile.signature(item):
                continue
            if position != newest_stored:
                revised = True
        if revised:
            return await self._reload(
                key, profile, series, loader, now, runtime, series.source_interval
            )
        newest_positions = sorted(profile.position(item) for item in closed)
        async with engine.session_scope(operation="write") as session:
            await self._write(session, profile, series, closed, replace=False)
            covered_to = self._covered_to(
                profile,
                newest_positions,
                profile.newest_closed(now),
                series.covered_to,
            )
            if profile.dataset == "iv":
                covered_to = max(
                    [series.covered_to, *newest_positions]
                    if newest_positions
                    else [series.covered_to]
                )
            fields: dict[str, Any] = {
                "synced_at": now,
                "sync_failed_at": None,
                "covered_to": covered_to,
            }
            if loaded.source_instrument:
                fields["source_instrument"] = loaded.source_instrument
            await repository.update_series(session, series.id, **fields)
        return False

    async def _reload(
        self,
        key: SeriesKey,
        profile: Profile,
        series: Series,
        loader: Loader[Any],
        now: datetime,
        runtime: _Runtime,
        source_interval: str | None = None,
    ) -> bool:
        assert series.covered_from is not None
        logger.info("History store: revision detected, reloading series %s", series.id)
        loaded = await loader(series.covered_from, now)
        closed, forming = self._split(profile, loaded.items, now)
        runtime.forming = forming
        if not closed:
            return False  # an empty answer must not wipe the stored rows
        positions = sorted(profile.position(item) for item in closed)
        async with engine.session_scope(operation="write") as session:
            await self._write(session, profile, series, closed, replace=True)
            fields: dict[str, Any] = {
                "synced_at": now,
                "sync_failed_at": None,
                "covered_to": max(
                    profile.newest_closed(now)
                    if profile.dataset == "prices"
                    else positions[-1],
                    positions[-1],
                ),
            }
            if profile.intraday:
                fields["covered_from"] = positions[0]
            if loaded.source_instrument:
                fields["source_instrument"] = loaded.source_instrument
            fields["source_interval"] = source_interval
            await repository.update_series(session, series.id, **fields)
        return True


history_sync = HistorySync()
