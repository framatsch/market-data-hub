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

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from urllib.parse import quote as url_quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response, StreamingResponse

from app.cache import cache
from app.config import settings
from app.dependencies import PriceServiceDep, symbol_param
from app.models.common import ResponseEnvelope
from app.utils.csv_export import to_csv
from app.utils.symbols import PRICE_TYPES, ParsedSymbol

router = APIRouter(prefix="/prices", tags=["Prices"])

PriceSymbol = Annotated[ParsedSymbol, Depends(symbol_param(PRICE_TYPES))]


@router.get("/{symbol}/last")
async def get_last_price(
    symbol: PriceSymbol,
    service: PriceServiceDep,
    provider: str | None = Query(
        None,
        description="Data provider: 'ibkr' or 'lseg'. Note: LSEG ignores market_data_type",
    ),
    market_data_type: int | None = Query(
        None,
        description="Market data type (IBKR only): 1=Live (Level 2), 2=Frozen, 3=Delayed (default). LSEG ignores this parameter.",
    ),
    format: str = "json",
) -> Any:
    """
    Get the latest price quote for a symbol.

    Symbol notation: `AAPL` (stock/ETF), `I:SPX` or `^SPX` (index), `F:ES`
    (front-month future). The response `symbol` is the canonical form. The optional
    `sec_type` query parameter (stock, etf, index, future) is accepted for legacy
    clients and must agree with any prefix.

    Query Parameters:
    - market_data_type: 1=Live (Level 2), 2=Frozen, 3=Delayed (default, free)
    - format: "json" (default) or "csv"

    Errors:
    - 501: the provider has no hub implementation for this instrument type
    - 403 PROVIDER_NOT_ENTITLED: the provider subscription does not cover it

    Provider notes:
    - IBKR: honors `market_data_type`; Level 1 requires a subscription
    - LSEG: ignores `market_data_type` and returns latest daily summary (historical_pricing)
    """
    provider = provider.lower() if provider else None
    quote = await service.get_latest_price(symbol, provider, market_data_type)

    if format.lower() == "csv":
        filename = f"{url_quote(symbol.canonical, safe='')}_last_price.csv"
        content_type, csv_data = to_csv(quote, filename)
        return StreamingResponse(
            iter([csv_data]),
            media_type=content_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    return ResponseEnvelope(data=quote)


@router.get("/{symbol}/history")
@cache(expire=settings.CACHE_TTL_HISTORICAL_OPEN_BAR_SECONDS)
async def get_historical_prices(
    symbol: PriceSymbol,
    service: PriceServiceDep,
    interval: str = "1d",
    start: datetime | None = None,
    end: datetime | None = None,
    extended_hours: bool = Query(
        False, description="Include extended trading hours (pre-market/after-hours)"
    ),
    provider: str | None = None,
    format: str = "json",
) -> Any:
    """
    Get historical price bars.

    Symbol notation: `AAPL`, `I:SPX` / `^SPX`, `F:ES` (provider continuous
    front-month series, unadjusted). Responses carry the canonical `symbol` and,
    where useful, the provider-native `source_instrument`.

    Query Parameters:
    - interval: "1d" (default), "1h", "5m", etc.
    - start: Start date (default: 30 days ago)
    - end: End date (default: now)
    - format: "json" (default) or "csv"

    Errors: 501 when the hub does not implement the type for the provider,
    403 PROVIDER_NOT_ENTITLED when the subscription does not cover it.
    """
    if not end:
        end = datetime.now(UTC)
    if not start:
        start = end - timedelta(days=30)

    provider = provider.lower() if provider else None
    bars = await service.get_historical_prices(
        symbol, interval, start, end, extended_hours, provider
    )

    if format.lower() == "csv":
        filename = f"{url_quote(symbol.canonical, safe='')}_history_{interval}.csv"
        content_type, csv_data = to_csv(bars, filename)
        return Response(
            content=csv_data,
            media_type=content_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    return ResponseEnvelope(data=bars)
