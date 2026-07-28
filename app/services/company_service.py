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

from typing import Any

import structlog

from app.models.company import CompanyProfile, CompanySummary
from app.providers.registry import get_registry


class CompanyService:
    def __init__(self, registry: Any = None) -> None:
        self.registry = registry or get_registry()

    async def get_company_profile(self, symbol: str, provider_name: str | None = None) -> CompanyProfile:
        provider = self.registry.get_company_provider(provider_name)
        structlog.contextvars.bind_contextvars(provider=provider.name)
        return await provider.get_company_profile(symbol)

    async def search_companies(self, query: str, provider_name: str | None = None) -> list[CompanySummary]:
        provider = self.registry.get_company_provider(provider_name)
        structlog.contextvars.bind_contextvars(provider=provider.name)
        return await provider.search_companies(query)

company_service = CompanyService()
