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

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from starlette.responses import Response

from app.dependencies import PriceServiceDep
from app.models.common import HealthResponse, MarketStatus, ResponseEnvelope
from app.observability.metrics import metrics_response
from app.providers.registry import get_registry

router = APIRouter(tags=["Meta"])
start_time = datetime.now()
PROMETHEUS_TEXT_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


@router.get("/health", response_model=HealthResponse)
async def health_check() -> Any:
    """Returns service health status."""
    uptime = (datetime.now() - start_time).total_seconds()
    return HealthResponse(status="OK", uptime_seconds=uptime)


@router.get(
    "/metrics",
    response_class=Response,
    responses={
        200: {
            "content": {
                "text/plain; version=0.0.4": {
                    "example": "# HELP mdh_http_requests_total Total HTTP requests handled by Market Data Hub.\n"
                    "# TYPE mdh_http_requests_total counter\n"
                }
            },
            "description": "Prometheus text exposition format",
        }
    },
)
async def get_metrics() -> Any:
    """Expose Prometheus metrics for scraping."""
    return Response(
        content=metrics_response(),
        headers={"Content-Type": PROMETHEUS_TEXT_CONTENT_TYPE},
    )


@router.get("/market-status", response_model=ResponseEnvelope[MarketStatus])
async def get_market_status(
    service: PriceServiceDep,
    provider: str | None = Query(
        None, description="Data provider (e.g., polygon, ibkr)"
    ),
) -> Any:
    """Returns current market status."""
    status = await service.get_market_status(provider_name=provider)
    return ResponseEnvelope(data=status)


@router.get("/providers", response_model=ResponseEnvelope[dict[str, Any]])
async def list_providers() -> Any:
    """Lists available providers and defaults.

    Available Providers:
    - price: "ibkr", "lseg", "polygon"
    - company: "finnhub", "lseg", "ibkr", "polygon"
    - options: "ibkr", "lseg", "polygon"
    - news: "finnhub", "lseg", "ibkr", "mock"

    Note: IBKR company data is limited to contract details. For detailed fundamentals, use LSEG.
    Note: Mock provider provides test data for development and testing.
    Note: Finnhub provides real-time news with sentiment analysis.
    """
    reg = get_registry()
    return ResponseEnvelope(
        data={
            "defaults": {
                "price": reg.default_price_provider,
                "company": reg.default_company_provider,
                "options": reg.default_options_provider,
                "news": reg.default_news_provider,
            },
            "available": {
                "price": ["ibkr", "lseg", "polygon", "prixe"],
                "company": ["finnhub", "lseg", "ibkr", "polygon"],
                "options": ["ibkr", "lseg", "polygon"],
                "news": ["finnhub", "lseg", "ibkr", "mock"],
            },
        }
    )
