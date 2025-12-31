from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter

from app.dependencies import PriceServiceDep
from app.models.price import PriceBar, PriceQuote
from app.models.common import ResponseEnvelope

router = APIRouter(prefix="/prices", tags=["Prices"])

@router.get("/{symbol}/last", response_model=ResponseEnvelope[PriceQuote])
async def get_last_price(
    symbol: str, 
    service: PriceServiceDep,
    provider: Optional[str] = None
):
    """Get the latest price quote for a symbol."""
    quote = await service.get_latest_price(symbol, provider)
    return ResponseEnvelope(data=quote)

@router.get("/{symbol}/history", response_model=ResponseEnvelope[List[PriceBar]])
async def get_historical_prices(
    symbol: str,
    service: PriceServiceDep,
    interval: str = "1d",
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    provider: Optional[str] = None
):
    """Get historical price bars."""
    if not end:
        end = datetime.now()
    if not start:
        start = end - timedelta(days=30)
        
    bars = await service.get_historical_prices(symbol, interval, start, end, provider)
    return ResponseEnvelope(data=bars)
