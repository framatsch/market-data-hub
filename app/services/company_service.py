from typing import List, Optional

from app.models.company import CompanyProfile, CompanySummary
from app.providers.registry import get_registry

class CompanyService:
    def __init__(self, registry=None):
        self.registry = registry or get_registry()

    async def get_company_profile(self, symbol: str, provider_name: Optional[str] = None) -> CompanyProfile:
        provider = self.registry.get_company_provider(provider_name)
        return await provider.get_company_profile(symbol)

    async def search_companies(self, query: str, provider_name: Optional[str] = None) -> List[CompanySummary]:
        provider = self.registry.get_company_provider(provider_name)
        return await provider.search_companies(query)

company_service = CompanyService()
