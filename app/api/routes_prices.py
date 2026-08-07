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

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.dependencies import PriceServiceDep
from app.models.common import ResponseEnvelope
from app.utils.csv_export import to_csv

router = APIRouter(prefix="/prices", tags=["Prices"])


@router.get("/{symbol}/last")
async def get_last_price(
    symbol: str,
    service: PriceServiceDep,
    provider: str | None = Query(
        None,
        description="Data provider: 'ibkr' or 'lseg'. Note: LSEG ignores market_data_type",
    ),
    sec_type: str = Query(
        "stock",
        description="Security type: 'stock' (default) or 'index'. For indices like ^RUT, use 'index'.",
    ),
    market_data_type: int | None = Query(
        None,
        description="Market data type (IBKR only): 1=Live (Level 2), 2=Frozen, 3=Delayed (default). LSEG ignores this parameter.",
    ),
    format: str = "json",
) -> Any:
    """
    Get the latest price quote for a symbol.

    Query Parameters:
    - market_data_type: 1=Live (Level 2), 2=Frozen, 3=Delayed (default, free)
    - format: "json" (default) or "csv"

    Provider notes:
    - IBKR: honors `market_data_type`; Level 1 requires subscription and will return 503 if unavailable
    - LSEG: ignores `market_data_type` and returns latest daily summary (historical_pricing)
    - For indices (^RUT, ^VIX, etc.), set sec_type='index' and remove ^ prefix from symbol
    """
    symbol = symbol.upper()
    provider = provider.lower() if provider else None
    sec_type = sec_type.lower()
    quote = await service.get_latest_price(symbol, provider, market_data_type, sec_type)

    if format.lower() == "csv":
        content_type, csv_data = to_csv(quote, f"{symbol}_last_price.csv")
        return StreamingResponse(
            iter([csv_data]),
            media_type=content_type,
            headers={
                "Content-Disposition": f"attachment; filename={symbol}_last_price.csv"
            },
        )

    return ResponseEnvelope(data=quote)


@router.get("/{symbol}/history")
async def get_historical_prices(
    symbol: str,
    service: PriceServiceDep,
    interval: str = "1d",
    start: datetime | None = None,
    end: datetime | None = None,
    extended_hours: bool = Query(
        False, description="Include extended trading hours (pre-market/after-hours)"
    ),
    provider: str | None = None,
    sec_type: str = Query("stock", description="Security type: 'stock' or 'index'"),
    format: str = "json",
) -> Any:
    """
    Get historical price bars.

    Query Parameters:
    - interval: "1d" (default), "1h", "5m", etc.
    - start: Start date (default: 30 days ago)
    - end: End date (default: now)
    - format: "json" (default) or "csv"
    """
    if not end:
        end = datetime.now()
    if not start:
        start = end - timedelta(days=30)

    symbol = symbol.upper()
    provider = provider.lower() if provider else None
    sec_type = sec_type.lower()
    bars = await service.get_historical_prices(
        symbol, interval, start, end, extended_hours, provider, sec_type
    )

    if format.lower() == "csv":
        content_type, csv_data = to_csv(bars, f"{symbol}_history_{interval}.csv")
        return StreamingResponse(
            iter([csv_data]),
            media_type=content_type,
            headers={
                "Content-Disposition": f"attachment; filename={symbol}_history_{interval}.csv"
            },
        )

    return ResponseEnvelope(data=bars)
