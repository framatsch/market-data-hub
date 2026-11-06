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

from datetime import date, timedelta
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.cache import cache
from app.config import settings
from app.dependencies import VolatilityServiceDep
from app.models.common import ResponseEnvelope
from app.models.volatility import (
    VolatilityHistory,
    VolatilitySecType,
    VolatilitySnapshot,
    VolatilityStats,
)
from app.utils.csv_export import to_csv

router = APIRouter(prefix="/volatility", tags=["Volatility"])


def _csv_response(data: Any, symbol: str, suffix: str) -> Response:
    filename = f"{quote(symbol, safe='')}_volatility{suffix}.csv"
    content_type, csv_data = to_csv(data, filename)
    return Response(
        content=csv_data,
        media_type=content_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{symbol}", response_model=ResponseEnvelope[VolatilitySnapshot])
@cache(expire=settings.CACHE_TTL_VOLATILITY_SECONDS, key="volatility:snapshot")
async def get_implied_volatility(
    symbol: str,
    service: VolatilityServiceDep,
    sec_type: VolatilitySecType = Query(
        "stock",
        description="Underlying security type; futures use an options root, indices do not use stock tickers.",
    ),
    ric: str | None = Query(
        None,
        description="LSEG-only explicit ATMIV RIC, returned verbatim and exempt from market validation.",
    ),
    provider: str | None = Query(
        None,
        description="Volatility provider override: lseg or ibkr; otherwise the configured default.",
    ),
    format: Literal["json", "csv"] = Query(
        "json",
        description="JSON envelope or CSV attachment; IV values remain decimal fractions.",
    ),
) -> Any:
    """Underlying IV in annualized decimal fractions (0.2676 = 26.76%), four places.

    LSEG is end-of-day (indices update roughly hourly): stocks/ETFs/indices use
    `{SYMBOL}ATMIV.U` (OPRA); futures use `{ROOT}ATMIV` without `.U`. `ric` is
    an explicit LSEG instrument override, e.g. GDAXATMIV.EX, and skips market
    validation. IBKR uses its live/delayed 30-day model and rejects `ric`.
    Unsupported tenors are null; this endpoint does not change price quotes.
    """
    symbol = symbol.upper()
    snapshot = await service.get_implied_volatility(
        symbol, sec_type, ric, provider.lower() if provider else None
    )
    if format == "csv":
        metadata = snapshot.model_dump(exclude={"implied"})
        return _csv_response(
            [{**metadata, **tenor.model_dump()} for tenor in snapshot.implied],
            symbol,
            "",
        )
    return ResponseEnvelope(data=snapshot)


@router.get("/{symbol}/history", response_model=ResponseEnvelope[VolatilityHistory])
@cache(expire=settings.CACHE_TTL_VOLATILITY_SECONDS, key="volatility:history")
async def get_implied_volatility_history(
    symbol: str,
    service: VolatilityServiceDep,
    start: date | None = Query(
        None, description="First daily point (default end minus 365 calendar days)."
    ),
    end: date | None = Query(None, description="Last daily point (default today)."),
    tenor_days: int = Query(
        30,
        description="Constant-maturity IV tenor: 30, 60 or 90 days; IBKR supports only 30.",
        json_schema_extra={"enum": [30, 60, 90]},
    ),
    sec_type: VolatilitySecType = Query(
        "stock",
        description="Underlying security type; IBKR futures history is unsupported.",
    ),
    ric: str | None = Query(
        None, description="LSEG-only explicit ATMIV instrument override."
    ),
    provider: str | None = Query(
        None,
        description="Volatility provider override: lseg or ibkr; otherwise the configured default.",
    ),
    format: Literal["json", "csv"] = Query(
        "json",
        description="JSON envelope or CSV attachment; IV values remain decimal fractions.",
    ),
) -> Any:
    """Daily end-of-day underlying IV, in four-place decimal fractions.

    The default range is end minus 365 calendar days through today. LSEG OPRA
    records use `.U`, futures omit it, and `ric` overrides the instrument.
    IBKR only supports stock/ETF/index history and a 30-day tenor. Missing
    points are omitted and results are ascending. Use one provider consistently.
    """
    end = end or date.today()
    start = start or end - timedelta(days=365)
    symbol = symbol.upper()
    history = await service.get_implied_volatility_history(
        symbol,
        start,
        end,
        tenor_days,
        sec_type,
        ric,
        provider.lower() if provider else None,
    )
    if format == "csv":
        metadata = history.model_dump(exclude={"points"})
        return _csv_response(
            [{**metadata, **point.model_dump()} for point in history.points],
            symbol,
            "_history",
        )
    return ResponseEnvelope(data=history)


@router.get("/{symbol}/stats", response_model=ResponseEnvelope[VolatilityStats])
@cache(expire=settings.CACHE_TTL_VOLATILITY_SECONDS, key="volatility:stats")
async def get_implied_volatility_stats(
    symbol: str,
    service: VolatilityServiceDep,
    window: int = Query(
        252,
        ge=20,
        le=756,
        description="Requested daily trading points (20–756); fewer available points may be used.",
    ),
    tenor_days: int = Query(
        30,
        description="IV tenor: 30, 60 or 90 days; IBKR supports only 30.",
        json_schema_extra={"enum": [30, 60, 90]},
    ),
    sec_type: VolatilitySecType = Query(
        "stock",
        description="Underlying security type; IBKR futures statistics are unsupported.",
    ),
    ric: str | None = Query(
        None, description="LSEG-only explicit ATMIV instrument override."
    ),
    provider: str | None = Query(
        None,
        description="Volatility provider override: lseg or ibkr; otherwise the configured default.",
    ),
    format: Literal["json", "csv"] = Query(
        "json",
        description="JSON envelope or CSV attachment; ranks are 0–100 and IV is fractional.",
    ),
) -> Any:
    """IV Rank and IV Percentile over the last window daily points (default 252).

    Current/min/max IV are four-place decimal fractions; IVR/IVP are 0–100
    with two places. IVR is sensitive to single outlier days; IVP is robust
    and counts strictly lower prior points, excluding current. There is no
    outlier filtering. Flat windows have null IVR; fewer than 20 points is 404.
    LSEG history is end-of-day; `.U` means OPRA, not futures. `ric` is LSEG-only.
    """
    symbol = symbol.upper()
    stats = await service.get_implied_volatility_stats(
        symbol,
        window,
        tenor_days,
        sec_type,
        ric,
        provider.lower() if provider else None,
    )
    if format == "csv":
        return _csv_response(stats, symbol, "_stats")
    return ResponseEnvelope(data=stats)
