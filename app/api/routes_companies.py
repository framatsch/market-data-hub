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

from typing import Any, List, Optional
from datetime import date, timedelta
import io
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.dependencies import CompanyServiceDep, NewsServiceDep
from app.models.company import CompanyProfile, CompanySummary
from app.models.common import ResponseEnvelope
from app.models.news import NewsResponse, NewsMetadata
from app.utils.csv_export import to_csv

router = APIRouter(prefix="/companies", tags=["Companies"])

@router.get("/search", response_model=ResponseEnvelope[List[CompanySummary]])
async def search_companies(
    q: str,
    service: CompanyServiceDep,
    provider: Optional[str] = None
) -> Any:
    """Search for companies by query string."""
    provider = provider.lower() if provider else None
    results = await service.search_companies(q, provider)
    return ResponseEnvelope(data=results)

@router.get("/{symbol}", response_model=ResponseEnvelope[CompanyProfile])
async def get_company_profile(
    symbol: str,
    service: CompanyServiceDep,
    provider: Optional[str] = None
) -> Any:
    """Get company profile information."""
    symbol = symbol.upper()
    provider = provider.lower() if provider else None
    profile = await service.get_company_profile(symbol, provider)
    return ResponseEnvelope(data=profile)


@router.get("/{symbol}/news", response_model=NewsResponse)
async def get_company_news(
    symbol: str,
    service: NewsServiceDep,
    provider: Optional[str] = Query(None, description="Data provider (finnhub, lseg, ibkr, mock)"),
    days: Optional[int] = Query(None, description="Last N days (overrides from/to dates)"),
    from_date: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    to_date: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    limit: int = Query(20, ge=1, le=100, description="Results per page (max 100)"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    language: str = Query("en", description="Language code (ISO 639-1: en, de, fr, etc.)"),
    category: Optional[str] = Query(None, description="Filter by category (earnings, merger, product, legal)"),
    format: str = Query("json", description="Response format (json, csv)")
) -> Any:
    """
    Get news articles for a company.

    **Time Range Priority:**
    1. If `days` is provided: Last N days from today (overrides from/to)
    2. If `from_date` and/or `to_date` provided: Use explicit range
    3. Default: Last 30 days

    **Examples:**
    - Last 7 days: `?days=7`
    - Last 30 days (default): `/companies/AAPL/news`
    - Specific range: `?from_date=2026-01-01&to_date=2026-01-04`
    - Earnings only: `?category=earnings`
    - CSV export: `?format=csv`
    - German news: `?language=de`
    - Pagination: `?limit=50&offset=50`
    - IBKR provider: `?provider=ibkr`
    """
    symbol = symbol.upper()
    provider = provider.lower() if provider else None
    response_provider = provider or service.registry.default_news_provider or "none"

    # 1. Determine date range (priority: days > explicit dates > default)
    if days:
        to_date_calc = date.today()
        from_date_calc = to_date_calc - timedelta(days=days)
    elif from_date or to_date:
        from_date_calc = from_date or (date.today() - timedelta(days=30))
        to_date_calc = to_date or date.today()
    else:
        # Default: last 30 days
        to_date_calc = date.today()
        from_date_calc = to_date_calc - timedelta(days=30)

    # 2. Fetch news articles
    articles = await service.get_company_news(
        symbol=symbol,
        from_date=from_date_calc,
        to_date=to_date_calc,
        provider_name=provider,
        limit=limit,
        offset=offset,
        language=language,
        category=category
    )

    # 4. Calculate metadata
    total = len(articles) + offset  # Simplified - actual total unknown without full scan
    has_more = len(articles) == limit  # If we got exactly limit, there may be more

    # 5. CSV export if requested
    if format.lower() == "csv":
        content_type, csv_bytes = to_csv(articles, filename=f"{symbol}_news.csv")
        return StreamingResponse(
            io.BytesIO(csv_bytes),
            media_type=content_type,
            headers={
                "Content-Disposition": f"attachment; filename={symbol}_news.csv"
            }
        )

    # 6. Return JSON response
    return NewsResponse(
        data=articles,
        meta=NewsMetadata(
            total=total,
            limit=limit,
            offset=offset,
            has_more=has_more,
            provider=response_provider,
            from_date=from_date_calc,
            to_date=to_date_calc
        )
    )
