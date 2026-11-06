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

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

VolatilitySecType = Literal["stock", "etf", "index", "future"]
VolatilityTenorDays = Literal[30, 60, 90]
IV_PRECISION = Decimal("0.0001")


def quantize_iv(value: Any) -> Decimal | None:
    """Normalize a positive, finite IV fraction to four decimal places."""
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0:
            return None
        return number.quantize(IV_PRECISION, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return None


def combine_iv(call: Any, put: Any, combined: Any = None) -> Decimal | None:
    """Use the mean of available sides, or a provider's combined IV."""
    values = [iv for value in (call, put) if (iv := quantize_iv(value)) is not None]
    if values:
        return quantize_iv(sum(values) / len(values))
    return quantize_iv(combined)


class ImpliedVolatilityTenor(BaseModel):
    tenor_days: VolatilityTenorDays
    iv_call: Decimal | None = None
    iv_put: Decimal | None = None
    iv: Decimal | None = None

    @field_validator("iv_call", "iv_put", "iv", mode="before")
    @classmethod
    def normalize_iv(cls, value: Any) -> Decimal | None:
        return quantize_iv(value)


def uniform_tenors(
    tenors: dict[int, ImpliedVolatilityTenor],
) -> list[ImpliedVolatilityTenor]:
    """Always expose 30/60/90 days, including null unsupported tenors."""
    return [
        tenors.get(days, ImpliedVolatilityTenor(tenor_days=days))
        for days in (30, 60, 90)
    ]


class VolatilitySnapshot(BaseModel):
    symbol: str
    sec_type: VolatilitySecType
    method: Literal["provider_atm_index", "provider_model_30d"]
    source_instrument: str
    underlying: str | None = None
    underlying_name: str | None = None
    market: str | None = None
    as_of: date | None = None
    implied: list[ImpliedVolatilityTenor]
    provider: str

    @field_validator("implied")
    @classmethod
    def normalize_tenors(
        cls, value: list[ImpliedVolatilityTenor]
    ) -> list[ImpliedVolatilityTenor]:
        return uniform_tenors({tenor.tenor_days: tenor for tenor in value})


class VolatilityPoint(BaseModel):
    date: date
    iv_call: Decimal | None = None
    iv_put: Decimal | None = None
    iv: Decimal | None = None

    @field_validator("iv_call", "iv_put", "iv", mode="before")
    @classmethod
    def normalize_iv(cls, value: Any) -> Decimal | None:
        return quantize_iv(value)


class VolatilityHistory(BaseModel):
    symbol: str
    sec_type: VolatilitySecType
    source_instrument: str
    tenor_days: VolatilityTenorDays
    points: list[VolatilityPoint]
    provider: str

    @field_validator("points")
    @classmethod
    def sort_points(cls, value: list[VolatilityPoint]) -> list[VolatilityPoint]:
        return sorted(value, key=lambda point: point.date)


class VolatilityStats(BaseModel):
    symbol: str
    sec_type: VolatilitySecType
    source_instrument: str
    tenor_days: VolatilityTenorDays
    provider: str
    window: int = Field(ge=20, le=756)
    window_points: int = Field(ge=20, le=756)
    window_start: date
    window_end: date
    current: Decimal
    min: Decimal
    max: Decimal
    iv_rank: Decimal | None
    iv_percentile: Decimal

    @field_validator("current", "min", "max", mode="before")
    @classmethod
    def normalize_iv(cls, value: Any) -> Decimal | None:
        return quantize_iv(value)

    @field_validator("iv_rank", "iv_percentile")
    @classmethod
    def normalize_rank(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
