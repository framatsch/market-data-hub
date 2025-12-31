from datetime import date
from decimal import Decimal
from typing import List, Literal, Optional
from pydantic import BaseModel

class OptionQuote(BaseModel):
    symbol: str
    underlying_symbol: str
    strike: Decimal
    expiry: date
    type: Literal["call", "put"]
    price: Decimal
    bid: Optional[Decimal] = None
    ask: Optional[Decimal] = None
    volume: Optional[int] = None
    open_interest: Optional[int] = None
    implied_volatility: Optional[float] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    provider: str

class OptionChain(BaseModel):
    underlying_symbol: str
    expiry: date
    options: List[OptionQuote]
    provider: str
