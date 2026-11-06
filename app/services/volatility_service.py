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
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TypedDict, cast

import structlog

from app.models.volatility import (
    VolatilityHistory,
    VolatilitySecType,
    VolatilitySnapshot,
    VolatilityStats,
    VolatilityTenorDays,
)
from app.providers.base import BaseVolatilityProvider
from app.providers.registry import ProviderRegistry, get_registry
from app.utils.errors import (
    CapabilityNotSupportedError,
    DataNotFoundError,
    DataValidationError,
)


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
        if sec_type not in {"stock", "etf", "index", "future"}:
            raise DataValidationError(f"Invalid volatility security type: {sec_type}")
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
        symbol: str,
        sec_type: VolatilitySecType = "stock",
        ric: str | None = None,
        provider_name: str | None = None,
    ) -> VolatilitySnapshot:
        async with self.registry.use_volatility_provider(provider_name) as provider:
            structlog.contextvars.bind_contextvars(provider=provider.name)
            self._check_support(provider, "snapshot", sec_type)
            return await provider.get_implied_volatility(symbol.upper(), sec_type, ric)

    async def get_implied_volatility_history(
        self,
        symbol: str,
        start: date,
        end: date,
        tenor_days: int = 30,
        sec_type: VolatilitySecType = "stock",
        ric: str | None = None,
        provider_name: str | None = None,
    ) -> VolatilityHistory:
        if start > end:
            raise DataValidationError("IV history start must not be after end")
        async with self.registry.use_volatility_provider(provider_name) as provider:
            structlog.contextvars.bind_contextvars(provider=provider.name)
            self._check_support(provider, "history", sec_type, tenor_days)
            return await provider.get_implied_volatility_history(
                symbol.upper(),
                start,
                end,
                cast(VolatilityTenorDays, tenor_days),
                sec_type,
                ric,
            )

    async def get_implied_volatility_stats(
        self,
        symbol: str,
        window: int = 252,
        tenor_days: int = 30,
        sec_type: VolatilitySecType = "stock",
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
        async with self.registry.use_volatility_provider(provider_name) as provider:
            structlog.contextvars.bind_contextvars(provider=provider.name)
            self._check_support(provider, "stats", sec_type, tenor_days)
            history = await provider.get_implied_volatility_history(
                symbol.upper(),
                start,
                end,
                cast(VolatilityTenorDays, tenor_days),
                sec_type,
                ric,
            )
        points = sorted(
            (
                point
                for point in history.points
                if point.iv is not None and point.iv > 0
            ),
            key=lambda point: point.date,
        )[-window:]
        if len(points) < 20:
            raise DataNotFoundError(
                "ImpliedVolatility",
                symbol.upper(),
                details={"reason": "insufficient_history", "points": len(points)},
            )
        return VolatilityStats(
            symbol=history.symbol,
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
