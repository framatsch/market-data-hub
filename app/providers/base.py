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

from abc import ABC, abstractmethod
from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional

from app.models.price import PriceBar, PriceQuote
from app.models.company import CompanyProfile, CompanySummary
from app.models.options import OptionChain, OptionQuote
from app.models.news import NewsArticle

class BasePriceProvider(ABC):
    @abstractmethod
    async def get_historical_prices(self, symbol: str, interval: str, start: datetime, end: datetime, sec_type: str = "stock") -> List[PriceBar]:
        """Fetch historical price bars."""
        pass

    @abstractmethod
    async def get_last_price(self, symbol: str, market_data_type: Optional[int] = None, sec_type: str = "stock") -> PriceQuote:
        """Fetch latest price quote."""
        pass

class BaseCompanyProvider(ABC):
    @abstractmethod
    async def get_company_profile(self, symbol: str) -> CompanyProfile:
        """Fetch company profile."""
        pass

    @abstractmethod
    async def search_companies(self, query: str) -> List[CompanySummary]:
        """Search for companies."""
        pass

class BaseOptionsProvider(ABC):
    @abstractmethod
    async def get_option_chain(
        self,
        symbol: str,
        expiry: date,
        min_strike: Optional[Decimal] = None,
        max_strike: Optional[Decimal] = None,
        right: Optional[Literal["call", "put"]] = None,
        market_data_type: Optional[int] = None
    ) -> OptionChain:
        """Fetch option chain for a given expiry."""
        pass

    @abstractmethod
    async def get_option_quote(self, symbol: str, option_id: str, market_data_type: Optional[int] = None) -> OptionQuote:
        """Fetch specific option quote."""
        pass


class BaseNewsProvider(ABC):
    """Abstract base class for news data providers."""

    @abstractmethod
    async def get_company_news(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
        limit: int = 20,
        offset: int = 0,
        language: str = "en",
        category: Optional[str] = None
    ) -> List[NewsArticle]:
        """
        Get news articles for a company.

        Args:
            symbol: Stock symbol
            from_date: Start date for news
            to_date: End date for news
            limit: Maximum number of articles to return
            offset: Pagination offset
            language: ISO 639-1 language code (e.g., "en", "de")
            category: Optional category filter (earnings, merger, product, etc.)

        Returns:
            List of news articles (sorted newest first)

        Raises:
            DataNotFoundError: If symbol not found
            ProviderError: If news retrieval fails
        """
        pass
