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

from app.models.company import CompanyProfile, CompanySummary
from app.observability.telemetry import bind_data_provider
from app.providers.registry import ProviderRegistry, get_registry
from app.utils.errors import DataNotFoundError
from app.utils.instrument_reference import REFERENCE_PROVIDER, reference_for
from app.utils.symbols import ParsedSymbol


class CompanyService:
    def __init__(self, registry: ProviderRegistry | None = None) -> None:
        self.registry = registry or get_registry()

    async def get_company_profile(
        self, symbol: ParsedSymbol, provider_name: str | None = None
    ) -> CompanyProfile:
        reference = reference_for(symbol)
        if symbol.sec_type == "index":
            # No provider serves index profiles; the curated table is the only source.
            if reference is None:
                raise DataNotFoundError("Index", symbol.canonical)
            bind_data_provider(REFERENCE_PROVIDER)
            return reference.profile(symbol.canonical)
        try:
            async with self.registry.use_company_provider(provider_name) as provider:
                bind_data_provider(provider.name)
                profile = await provider.get_company_profile(symbol.root)
        except DataNotFoundError:
            if reference is None:
                raise
            bind_data_provider(REFERENCE_PROVIDER)
            return reference.profile(symbol.canonical)
        if reference is None:
            return profile
        # Providers leave sector and description empty for ETFs; fill only the gaps.
        return profile.model_copy(
            update={
                "description": profile.description or reference.description,
                "sector": profile.sector or reference.sector,
            }
        )

    async def search_companies(
        self, query: str, provider_name: str | None = None
    ) -> list[CompanySummary]:
        async with self.registry.use_company_provider(provider_name) as provider:
            bind_data_provider(provider.name)
            return await provider.search_companies(query)


company_service = CompanyService()
