from decimal import Decimal
from typing import Literal, Optional
from datetime import date, timedelta
from fastapi import APIRouter, Query

from app.dependencies import OptionsServiceDep
from app.models.options import OptionChain, OptionQuote
from app.models.common import ResponseEnvelope

router = APIRouter(prefix="/options", tags=["Options"])

@router.get("/{symbol}/chain", response_model=ResponseEnvelope[OptionChain])
async def get_option_chain(
    symbol: str,
    service: OptionsServiceDep,
    expiry: Optional[date] = None,
    min_strike: Optional[Decimal] = Query(None, description="Minimum strike price to include"),
    max_strike: Optional[Decimal] = Query(None, description="Maximum strike price to include"),
    right: Optional[Literal["call", "put"]] = Query(None, description="Filter by option type (call or put)"),
    include_level2: bool = Query(False, description="Include Level 2 market data (requires subscription)"),
    provider: Optional[str] = None
):
    """Get option chain for a symbol and expiry.

    Note:
    - If include_level2=true and you don't have Level 2 subscription, the API will gracefully fallback to Level 1
    - Errors will be logged but won't prevent data retrieval
    """
    if not expiry:
        # Default to a future date
        expiry = date.today() + timedelta(days=30)
    chain = await service.get_option_chain(
        symbol,
        expiry,
        provider_name=provider,
        min_strike=min_strike,
        max_strike=max_strike,
        right=right,
        include_level2=include_level2
    )
    return ResponseEnvelope(data=chain)

@router.get("/{symbol}/quote/{option_id}", response_model=ResponseEnvelope[OptionQuote])
async def get_option_quote(
    symbol: str,
    option_id: str,
    service: OptionsServiceDep,
    include_level2: bool = Query(False, description="Include Level 2 market data (requires subscription)"),
    provider: Optional[str] = None
):
    """Get a specific option quote.

    Note:
    - If include_level2=true and you don't have Level 2 subscription, the API will gracefully fallback to Level 1
    - Errors will be logged but won't prevent data retrieval
    """
    quote = await service.get_option_quote(symbol, option_id, provider, include_level2=include_level2)
    return ResponseEnvelope(data=quote)
