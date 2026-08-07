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
from typing import Any, Literal

from app.models.common import MarketStatus
from app.models.company import CompanyProfile, CompanySummary
from app.models.news import NewsArticle
from app.models.options import OptionChain, OptionQuote
from app.models.price import PriceBar, PriceQuote


class BasePriceProvider(ABC):
    name = "none"

    def configure(self, config: Any) -> None:
        """Apply runtime configuration from the admin repository."""
        self._runtime_config = config
        _apply_runtime_config_defaults(self, config)

    @abstractmethod
    async def get_historical_prices(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
        extended_hours: bool = False,
        sec_type: str = "stock",
    ) -> list[PriceBar]:
        """Fetch historical price bars."""

    @abstractmethod
    async def get_last_price(
        self, symbol: str, market_data_type: int | None = None, sec_type: str = "stock"
    ) -> PriceQuote:
        """Fetch latest price quote."""

    @abstractmethod
    async def test_connection(self) -> dict[str, Any]:
        """Test provider connectivity and return status_code/success/message/details."""

    async def get_market_status(self) -> MarketStatus:
        """Fetch current market status."""
        raise NotImplementedError("Market status not implemented for this provider")


class BaseCompanyProvider(ABC):
    name = "none"

    def configure(self, config: Any) -> None:
        """Apply runtime configuration from the admin repository."""
        self._runtime_config = config
        _apply_runtime_config_defaults(self, config)

    @abstractmethod
    async def get_company_profile(self, symbol: str) -> CompanyProfile:
        """Fetch company profile."""

    @abstractmethod
    async def search_companies(self, query: str) -> list[CompanySummary]:
        """Search for companies."""

    @abstractmethod
    async def test_connection(self) -> dict[str, Any]:
        """Test provider connectivity and return status_code/success/message/details."""


class BaseOptionsProvider(ABC):
    name = "none"

    def configure(self, config: Any) -> None:
        """Apply runtime configuration from the admin repository."""
        self._runtime_config = config
        _apply_runtime_config_defaults(self, config)

    @abstractmethod
    async def get_option_chain(
        self,
        symbol: str,
        expiry: date,
        min_strike: Decimal | None = None,
        max_strike: Decimal | None = None,
        right: Literal["call", "put"] | None = None,
        market_data_type: int | None = None,
    ) -> OptionChain:
        """Fetch option chain for a given expiry."""

    @abstractmethod
    async def get_option_quote(
        self, symbol: str, option_id: str, market_data_type: int | None = None
    ) -> OptionQuote:
        """Fetch specific option quote."""

    @abstractmethod
    async def test_connection(self) -> dict[str, Any]:
        """Test provider connectivity and return status_code/success/message/details."""


class BaseNewsProvider(ABC):
    """Abstract base class for news data providers."""

    name = "none"

    def configure(self, config: Any) -> None:
        """Apply runtime configuration from the admin repository."""
        self._runtime_config = config
        _apply_runtime_config_defaults(self, config)

    @abstractmethod
    async def get_company_news(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
        limit: int = 20,
        offset: int = 0,
        language: str = "en",
        category: str | None = None,
    ) -> list[NewsArticle]:
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

    @abstractmethod
    async def test_connection(self) -> dict[str, Any]:
        """Test provider connectivity and return status_code/success/message/details."""


def _apply_runtime_config_defaults(provider: object, config: Any) -> None:
    for attr in (
        "timeout_seconds",
        "retry_count",
        "retry_backoff_seconds",
        "rate_limit_per_sec",
        "circuit_breaker_enabled",
        "circuit_breaker_failure_threshold",
        "circuit_breaker_reset_seconds",
        "connection_config",
    ):
        setattr(provider, attr, getattr(config, attr))
