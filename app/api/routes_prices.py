from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.dependencies import PriceServiceDep
from app.models.common import ResponseEnvelope
from app.utils.csv_export import to_csv

router = APIRouter(prefix="/prices", tags=["Prices"])

@router.get("/{symbol}/last")
async def get_last_price(
    symbol: str,
    service: PriceServiceDep,
    provider: Optional[str] = None,
    format: str = "json"
):
    """
    Get the latest price quote for a symbol.

    Query Parameters:
    - format: "json" (default) or "csv"
    """
    quote = await service.get_latest_price(symbol, provider)

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

    bars = await service.get_historical_prices(symbol, interval, start, end, provider)

    if format.lower() == "csv":
        content_type, csv_data = to_csv(bars, f"{symbol}_history_{interval}.csv")
        return StreamingResponse(
            iter([csv_data]),
            media_type=content_type,
            headers={"Content-Disposition": f"attachment; filename={symbol}_history_{interval}.csv"}
        )

    return ResponseEnvelope(data=bars)
