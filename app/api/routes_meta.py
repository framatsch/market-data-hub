from datetime import datetime
from fastapi import APIRouter
from app.models.common import HealthResponse, ResponseEnvelope
from app.config import settings

router = APIRouter(tags=["Meta"])
start_time = datetime.now()

@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Returns service health status."""
    uptime = (datetime.now() - start_time).total_seconds()
    return HealthResponse(status="OK", uptime_seconds=uptime)

@router.get("/providers", response_model=ResponseEnvelope[dict])
async def list_providers():
    """Lists available providers and defaults.

    Available Providers:
    - price: "ibkr" (primary), "lseg" (secondary)
    - company: "lseg" (primary), "ibkr" (basic lookup only)
    - options: "ibkr" (primary), "lseg" (secondary)
    - news: "finnhub" (primary, 60 calls/min), "lseg" (secondary), "ibkr" (basic), "mock" (testing)

    Note: IBKR company data is limited to contract details. For detailed fundamentals, use LSEG.
    Note: Mock provider provides test data for development and testing.
    Note: Finnhub provides real-time news with sentiment analysis. Free tier: 60 calls/min.
    """
    return ResponseEnvelope(data={
        "defaults": {
            "price": settings.DEFAULT_PRICE_PROVIDER,
            "company": settings.DEFAULT_COMPANY_PROVIDER,
            "options": settings.DEFAULT_OPTIONS_PROVIDER,
            "news": "finnhub"
        },
        "available": {
            "price": ["ibkr", "lseg"],
            "company": ["lseg", "ibkr"],
            "options": ["ibkr", "lseg"],
            "news": ["finnhub", "lseg", "ibkr", "mock"]
        }
    })
