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
    open: Optional[Decimal] = None
    high: Optional[Decimal] = None
    low: Optional[Decimal] = None
    volume: Optional[int] = None
    is_market_open: Optional[bool] = None

    @property
    def last_price(self) -> Decimal:
        return self.price

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

    @property
    def timestamp(self) -> datetime:
        if self.start.tzinfo is not None:
            return self.start.replace(tzinfo=None)
        return self.start
