from typing import List, Optional
from fastapi import APIRouter, Query

from app.dependencies import CompanyServiceDep
from app.models.company import CompanyProfile, CompanySummary
from app.models.common import ResponseEnvelope

router = APIRouter(prefix="/companies", tags=["Companies"])

@router.get("/search", response_model=ResponseEnvelope[List[CompanySummary]])
async def search_companies(
    q: str, 
    service: CompanyServiceDep,
    provider: Optional[str] = None
):
    """Search for companies by query string."""
    results = await service.search_companies(q, provider)
    return ResponseEnvelope(data=results)

@router.get("/{symbol}", response_model=ResponseEnvelope[CompanyProfile])
async def get_company_profile(
    symbol: str, 
    service: CompanyServiceDep,
    provider: Optional[str] = None
):
    """Get company profile information."""
    profile = await service.get_company_profile(symbol, provider)
    return ResponseEnvelope(data=profile)
