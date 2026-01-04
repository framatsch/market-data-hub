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
    - company: "lseg" (primary)
    - options: "ibkr" (primary), "lseg" (secondary)
    """
    return ResponseEnvelope(data={
        "defaults": {
            "price": settings.DEFAULT_PRICE_PROVIDER,
            "company": settings.DEFAULT_COMPANY_PROVIDER,
            "options": settings.DEFAULT_OPTIONS_PROVIDER,
        },
        "available": {
            "price": ["ibkr", "lseg"],
            "company": ["lseg"],
            "options": ["ibkr", "lseg"]
        }
    })
