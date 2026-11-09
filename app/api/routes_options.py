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

from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal
from urllib.parse import quote as url_quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response, StreamingResponse

from app.cache import cache
from app.config import settings
from app.dependencies import OptionsServiceDep, symbol_param
from app.models.common import ResponseEnvelope
from app.utils.csv_export import to_csv
from app.utils.symbols import OPTION_UNDERLYING_TYPES, ParsedSymbol, strip_option_prefix

router = APIRouter(prefix="/options", tags=["Options"])

UnderlyingSymbol = Annotated[
    ParsedSymbol, Depends(symbol_param(OPTION_UNDERLYING_TYPES))
]


@router.get("/{symbol}/chain")
@cache(expire=settings.CACHE_TTL_OPTION_CHAIN_SECONDS)
async def get_option_chain(
    symbol: UnderlyingSymbol,
    service: OptionsServiceDep,
    expiry: date | None = None,
    min_strike: Decimal | None = Query(
        None, description="Minimum strike price to include"
    ),
    max_strike: Decimal | None = Query(
        None, description="Maximum strike price to include"
    ),
    right: Literal["call", "put"] | None = Query(
        None, description="Filter by option type (call or put)"
    ),
    market_data_type: int | None = Query(
        None,
        description="Market data type: 1=Live (Level 2), 2=Frozen, 3=Delayed (default, free)",
    ),
    provider: str | None = None,
    format: str = "json",
) -> Any:
    """Get option chain for a symbol and expiry.

    The underlying may be a stock/ETF (`AAPL`) or an index (`I:SPX`, `^SPX`);
    the response `underlying_symbol` is canonical. Providers without an index
    option implementation answer 501.

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
        market_data_type=market_data_type,
    )

    if format.lower() == "csv":
        filename = f"{url_quote(symbol.canonical, safe='')}_options_chain_{expiry}.csv"
        content_type, csv_data = to_csv(chain.model_dump(), filename)
        return Response(
            content=csv_data,
            media_type=content_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    return ResponseEnvelope(data=chain)


@router.get("/{symbol}/quote/{option_id}")
async def get_option_quote(
    symbol: UnderlyingSymbol,
    option_id: str,
    service: OptionsServiceDep,
    market_data_type: int | None = Query(
        None,
        description="Market data type: 1=Live (Level 2), 2=Frozen, 3=Delayed (default, free)",
    ),
    provider: str | None = None,
    format: str = "json",
) -> Any:
    """Get a specific option quote.

    `option_id` may carry the `O:` prefix (`O:AAPL250117C00150000`), which is
    stripped before the provider call.

    Query Parameters:
    - market_data_type: 1=Live (requires Level 2 subscription), 2=Frozen (OPRA), 3=Delayed (default, free)
    - format: "json" (default) or "csv"

    Note:
    - If market_data_type is not specified, uses default from config (currently 3=Delayed)
    - Error 10091 warnings are normal if requesting data without proper subscription - system gracefully degrades
    """
    option_id = strip_option_prefix(option_id)
    provider = provider.lower() if provider else None
    quote = await service.get_option_quote(
        symbol, option_id, provider, market_data_type=market_data_type
    )

    if format.lower() == "csv":
        content_type, csv_data = to_csv(quote, f"{option_id}_quote.csv")
        return StreamingResponse(
            iter([csv_data]),
            media_type=content_type,
            headers={
                "Content-Disposition": f"attachment; filename={option_id}_quote.csv"
            },
        )

    return ResponseEnvelope(data=quote)
