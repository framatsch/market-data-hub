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

import math
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, TypedDict, cast

import structlog

from app import response_meta
from app.models.volatility import (
    VolatilityHistory,
    VolatilitySecType,
    VolatilitySnapshot,
    VolatilityStats,
    VolatilityTenorDays,
)
from app.observability.metrics import record_history_store_read
from app.providers.base import BaseVolatilityProvider
from app.providers.registry import ProviderRegistry, get_registry
from app.store import engine
from app.store.repository import SeriesKey
from app.store.sync import Loaded, Profile, history_sync
from app.utils.errors import (
    AppError,
    CapabilityNotSupportedError,
    DataNotFoundError,
    DataValidationError,
)
from app.utils.symbols import ParsedSymbol


class _IVStatistics(TypedDict):
    current: Decimal
    min: Decimal
    max: Decimal
    iv_rank: Decimal | None
    iv_percentile: Decimal


def _iv_statistics(values: list[Decimal]) -> _IVStatistics:
    """IVR uses min/max; IVP counts strictly lower prior points (no outlier filter)."""
    current, low, high = values[-1], min(values), max(values)
    rank = None if high == low else (current - low) / (high - low) * 100
    percentile = (
        Decimal(sum(value < current for value in values[:-1])) / (len(values) - 1) * 100
        if len(values) > 1
        else Decimal(0)
    )
    return {
        "current": current,
        "min": low,
        "max": high,
        "iv_rank": rank.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if rank is not None
        else None,
        "iv_percentile": percentile.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
    }


class VolatilityService:
    def __init__(self, registry: ProviderRegistry | None = None) -> None:
        self.registry = registry or get_registry()

    @staticmethod
    def _check_support(
        provider: BaseVolatilityProvider,
        operation: str,
        sec_type: VolatilitySecType,
        tenor_days: int | None = None,
    ) -> None:
        if tenor_days is not None and tenor_days not in (30, 60, 90):
            raise DataValidationError("IV tenor must be 30, 60 or 90 days")
        supported = (
            provider.volatility_sec_types
            if operation == "snapshot"
            else provider.volatility_history_sec_types
        )
        if sec_type not in supported:
            raise CapabilityNotSupportedError(
                provider.name,
                operation,
                sec_type=sec_type,
                tenor_days=tenor_days,
                supported=sorted(supported),
            )
        if tenor_days is not None and tenor_days not in provider.volatility_tenors:
            raise CapabilityNotSupportedError(
                provider.name,
                operation,
                sec_type=sec_type,
                tenor_days=tenor_days,
                supported=sorted(provider.volatility_tenors),
            )

    async def get_implied_volatility(
        self,
        symbol: ParsedSymbol,
        ric: str | None = None,
        provider_name: str | None = None,
    ) -> VolatilitySnapshot:
        sec_type = cast(VolatilitySecType, symbol.sec_type)
        async with self.registry.use_volatility_provider(provider_name) as provider:
            structlog.contextvars.bind_contextvars(provider=provider.name)
            self._check_support(provider, "snapshot", sec_type)
            snapshot = await provider.get_implied_volatility(symbol.root, sec_type, ric)
            return snapshot.model_copy(update={"symbol": symbol.canonical})

    async def _load_history(
        self,
        symbol: ParsedSymbol,
        start: date,
        end: date,
        tenor_days: int,
        ric: str | None,
        provider_name: str | None,
        operation: str = "history",
    ) -> VolatilityHistory:
        sec_type = cast(VolatilitySecType, symbol.sec_type)
        async with self.registry.use_volatility_provider(provider_name) as provider:
            structlog.contextvars.bind_contextvars(provider=provider.name)
            self._check_support(provider, operation, sec_type, tenor_days)
            history = await provider.get_implied_volatility_history(
                symbol.root,
                start,
                end,
                cast(VolatilityTenorDays, tenor_days),
                sec_type,
                ric,
            )
        response_meta.current().record_fetch()
        return history.model_copy(update={"symbol": symbol.canonical})

    async def _stored_history(
        self,
        symbol: ParsedSymbol,
        start: date,
        end: date,
        tenor_days: int,
        ric: str | None,
        provider_name: str | None,
        operation: str = "history",
    ) -> VolatilityHistory | None:
        """History through the store; None when the store is not usable."""
        effective = provider_name or self.registry.default_volatility_provider
        if not effective or not engine.store_enabled():
            return None
        key = SeriesKey(
            "iv", symbol.canonical, effective, "1d", False, tenor_days, ric or ""
        )
        statics: dict[str, Any] = {}

        async def loader(load_start: datetime, load_end: datetime) -> Loaded[Any]:
            history = await self._load_history(
                symbol,
                load_start.date(),
                load_end.date(),
                tenor_days,
                ric,
                effective,
                operation,
            )
            statics["history"] = history
            return Loaded(
                items=history.points,
                source_instrument=history.source_instrument,
                sec_type=symbol.sec_type,
            )

        meta = response_meta.current()
        served = await history_sync.serve(
            key,
            Profile("iv", "1d"),
            datetime.combine(start, time(), UTC),
            datetime.combine(end, time(), UTC),
            loader,
            force=meta.no_cache,
            sec_type=symbol.sec_type,
        )
        if served is None:
            return None
        if served.data_as_of is not None:
            meta.data_as_of = served.data_as_of
        if served.stale:
            meta.mark_stale(served.stale_reason or "PROVIDER_ERROR")
        series = served.series
        loaded: VolatilityHistory | None = statics.get("history")
        return VolatilityHistory(
            symbol=symbol.canonical,
            sec_type=cast(VolatilitySecType, symbol.sec_type),
            source_instrument=(
                loaded.source_instrument
                if loaded is not None
                else (series.source_instrument if series else None) or ""
            ),
            tenor_days=cast(VolatilityTenorDays, tenor_days),
            points=served.items,
            provider=effective,
        )

    async def get_implied_volatility_history(
        self,
        symbol: ParsedSymbol,
        start: date,
        end: date,
        tenor_days: int = 30,
        ric: str | None = None,
        provider_name: str | None = None,
    ) -> VolatilityHistory:
        if start > end:
            raise DataValidationError("IV history start must not be after end")
        return await self._history(
            symbol, start, end, tenor_days, ric, provider_name, "history"
        )

    async def _history(
        self,
        symbol: ParsedSymbol,
        start: date,
        end: date,
        tenor_days: int,
        ric: str | None,
        provider_name: str | None,
        operation: str,
    ) -> VolatilityHistory:
        stored = await self._stored_history(
            symbol, start, end, tenor_days, ric, provider_name, operation
        )
        if stored is not None:
            return stored
        record_history_store_read("iv", "bypass")
        return await self._load_history(
            symbol, start, end, tenor_days, ric, provider_name, operation
        )

    async def get_implied_volatility_stats(
        self,
        symbol: ParsedSymbol,
        window: int = 252,
        tenor_days: int = 30,
        ric: str | None = None,
        provider_name: str | None = None,
    ) -> VolatilityStats:
        if (
            not isinstance(window, int)
            or isinstance(window, bool)
            or not 20 <= window <= 756
        ):
            raise DataValidationError(
                "IV statistics window must be 20–756 trading-day points"
            )
        end = date.today()
        start = end - timedelta(days=math.ceil(window * 365 / 252) + 14)
        history = await self._history(
            symbol, start, end, tenor_days, ric, provider_name, "stats"
        )
        points = sorted(
            (
                point
                for point in history.points
                if point.iv is not None and point.iv > 0
            ),
            key=lambda point: point.date,
        )[-window:]
        meta = response_meta.current()
        if len(points) < 20:
            if meta.stale:
                raise AppError(
                    "Provider unavailable and too little stored IV history",
                    meta.stale_reason or "PROVIDER_ERROR",
                )
            raise DataNotFoundError(
                "ImpliedVolatility",
                symbol.canonical,
                details={"reason": "insufficient_history", "points": len(points)},
            )
        return VolatilityStats(
            symbol=symbol.canonical,
            sec_type=history.sec_type,
            source_instrument=history.source_instrument,
            tenor_days=history.tenor_days,
            provider=history.provider,
            window=window,
            window_points=len(points),
            window_start=points[0].date,
            window_end=points[-1].date,
            **_iv_statistics([cast(Decimal, point.iv) for point in points]),
        )
