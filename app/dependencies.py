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

from functools import lru_cache
from typing import Annotated
from fastapi import Depends

from app.services.price_service import PriceService
from app.services.company_service import CompanyService
from app.services.options_service import OptionsService
from app.services.news_service import NewsService, news_service
from app.providers.registry import get_provider as _get_provider
from app.providers.finnhub import FinnhubProvider

@lru_cache
def get_price_service() -> PriceService:
    return PriceService()

@lru_cache
def get_company_service() -> CompanyService:
    return CompanyService()

@lru_cache
def get_options_service() -> OptionsService:
    return OptionsService()

@lru_cache
def get_news_service() -> NewsService:
    return news_service

PriceServiceDep = Annotated[PriceService, Depends(get_price_service)]
CompanyServiceDep = Annotated[CompanyService, Depends(get_company_service)]
OptionsServiceDep = Annotated[OptionsService, Depends(get_options_service)]
NewsServiceDep = Annotated[NewsService, Depends(get_news_service)]


def get_provider(provider_type: str, name: str | None = None):
    return _get_provider(provider_type, name)


def get_company_provider() -> FinnhubProvider:
    """Return the provider used for company/news data (use Finnhub only)."""
    # Always use Finnhub for news/company data (LSEG removed)
    return FinnhubProvider()
