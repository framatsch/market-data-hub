from decimal import Decimal
from typing import Literal, Optional
from datetime import date
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.dependencies import OptionsServiceDep
from app.models.common import ResponseEnvelope
from app.utils.csv_export import to_csv

router = APIRouter(prefix="/options", tags=["Options"])

@router.get("/{symbol}/chain")
async def get_option_chain(
    symbol: str,
    service: OptionsServiceDep,
    expiry: Optional[date] = None,
    min_strike: Optional[Decimal] = Query(None, description="Minimum strike price to include"),
    max_strike: Optional[Decimal] = Query(None, description="Maximum strike price to include"),
    right: Optional[Literal["call", "put"]] = Query(None, description="Filter by option type (call or put)"),
    market_data_type: Optional[int] = Query(None, description="Market data type: 1=Live (Level 2), 2=Frozen, 3=Delayed (default, free)"),
    provider: Optional[str] = None,
    format: str = "json"
):
    """Get option chain for a symbol and expiry.

    Query Parameters:
    - expiry: Option expiration date (default: today)
    - min_strike: Filter by minimum strike price
    - max_strike: Filter by maximum strike price
    - right: Filter by option type ("call" or "put")
    - market_data_type: 1=Live (requires Level 2 subscription), 2=Frozen (OPRA), 3=Delayed (default, free)
    - format: "json" (default) or "csv"

    Note:
    - If market_data_type is not specified, uses default from config (currently 3=Delayed)
    - Error 10091 warnings are normal if requesting data without proper subscription - system gracefully degrades
    """
    symbol = symbol.upper()
    provider = provider.lower() if provider else None
    if not expiry:
        # Default to today
        expiry = date.today()
    chain = await service.get_option_chain(
        symbol,
        expiry,
        provider_name=provider,
        min_strike=min_strike,
        max_strike=max_strike,
        right=right,
        market_data_type=market_data_type
    )

    if format.lower() == "csv":
        content_type, csv_data = to_csv(chain.model_dump(), f"{symbol}_options_chain_{expiry}.csv")
        return StreamingResponse(
            iter([csv_data]),
            media_type=content_type,
            headers={"Content-Disposition": f"attachment; filename={symbol}_options_chain_{expiry}.csv"}
        )

    return ResponseEnvelope(data=chain)

@router.get("/{symbol}/quote/{option_id}")
async def get_option_quote(
    symbol: str,
    option_id: str,
    service: OptionsServiceDep,
    market_data_type: Optional[int] = Query(None, description="Market data type: 1=Live (Level 2), 2=Frozen, 3=Delayed (default, free)"),
    provider: Optional[str] = None,
    format: str = "json"
):
    """Get a specific option quote.

    Query Parameters:
    - market_data_type: 1=Live (requires Level 2 subscription), 2=Frozen (OPRA), 3=Delayed (default, free)
    - format: "json" (default) or "csv"

    Note:
    - If market_data_type is not specified, uses default from config (currently 3=Delayed)
    - Error 10091 warnings are normal if requesting data without proper subscription - system gracefully degrades
    """
    symbol = symbol.upper()
    provider = provider.lower() if provider else None
    quote = await service.get_option_quote(symbol, option_id, provider, market_data_type=market_data_type)

    if format.lower() == "csv":
        content_type, csv_data = to_csv(quote, f"{option_id}_quote.csv")
        return StreamingResponse(
            iter([csv_data]),
            media_type=content_type,
            headers={"Content-Disposition": f"attachment; filename={option_id}_quote.csv"}
        )

    return ResponseEnvelope(data=quote)
