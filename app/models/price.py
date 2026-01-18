from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel

class PriceQuote(BaseModel):
    symbol: str
    price: Decimal
    currency: str
    timestamp: datetime
    provider: str
    bid: Optional[Decimal] = None
    ask: Optional[Decimal] = None
    volume: Optional[int] = None
    is_market_open: Optional[bool] = None

class PriceBar(BaseModel):
    symbol: str
    start: datetime
    end: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    provider: str
