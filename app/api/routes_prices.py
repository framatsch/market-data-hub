from datetime import datetime, timedelta
from typing import Optional
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
    provider: Optional[str] = Query(
        None,
        description="Data provider: 'ibkr', 'lseg', or 'schwab'. Note: LSEG and Schwab ignore market_data_type"
    ),
    sec_type: str = Query(
        "stock",
        description="Security type: 'stock' (default) or 'index'. For indices like ^RUT, use 'index'."
    ),
    market_data_type: Optional[int] = Query(
        None,
        description="Market data type (IBKR only): 1=Live (Level 2), 2=Frozen, 3=Delayed (default). LSEG ignores this parameter."
    ),
    format: str = "json"
):
    """
    Get the latest price quote for a symbol.

    Query Parameters:
    - market_data_type: 1=Live (Level 2), 2=Frozen, 3=Delayed (default, free)
    - format: "json" (default) or "csv"

    Provider notes:
    - IBKR: honors `market_data_type`; Level 1 requires subscription and will return 503 if unavailable
    - LSEG: ignores `market_data_type` and returns latest daily summary (historical_pricing)
    - Schwab: ignores `market_data_type`; returns delayed quote data from Schwab API
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
            headers={"Content-Disposition": f"attachment; filename={symbol}_last_price.csv"}
        )

    return ResponseEnvelope(data=quote)

@router.get("/{symbol}/history")
async def get_historical_prices(
    symbol: str,
    service: PriceServiceDep,
    interval: str = "1d",
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    provider: Optional[str] = None,
    sec_type: str = Query("stock", description="Security type: 'stock' or 'index'"),
    format: str = "json"
):
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
    bars = await service.get_historical_prices(symbol, interval, start, end, provider, sec_type)

    if format.lower() == "csv":
        content_type, csv_data = to_csv(bars, f"{symbol}_history_{interval}.csv")
        return StreamingResponse(
            iter([csv_data]),
            media_type=content_type,
            headers={"Content-Disposition": f"attachment; filename={symbol}_history_{interval}.csv"}
        )

    return ResponseEnvelope(data=bars)
