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
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime
from decimal import Decimal
from functools import wraps
from typing import Any, Literal

from app.models.common import MarketStatus
from app.models.company import CompanyProfile, CompanySummary
from app.models.earnings import EarningsEvent
from app.models.news import NewsArticle
from app.models.options import OptionChain, OptionQuote
from app.models.price import PriceBar, PriceQuote
from app.models.volatility import (
    VolatilityHistory,
    VolatilitySecType,
    VolatilitySnapshot,
    VolatilityTenorDays,
)
from app.observability.telemetry import PROVIDER_OPERATIONS, current_telemetry, span
from app.utils.errors import CapabilityNotSupportedError

_inside_provider_call = ContextVar("mdh_inside_provider_call", default=False)


@contextmanager
def suppress_provider_timing() -> Iterator[None]:
    token = _inside_provider_call.set(True)
    try:
        yield
    finally:
        _inside_provider_call.reset(token)


def _observed(method: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    @wraps(method)
    async def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        if _inside_provider_call.get():
            return await method(self, *args, **kwargs)
        with suppress_provider_timing():
            if (telemetry := current_telemetry()) is not None:
                telemetry.provider_names.add(self.name)
            async with span("provider", method.__name__, provider=self.name):
                return await method(self, *args, **kwargs)

    wrapped.__dict__["_mdh_observed"] = True
    return wrapped


class _ObservedProvider(ABC):
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # A single cooperative hook covers providers with multiple capabilities.
        for operation in PROVIDER_OPERATIONS & cls.__dict__.keys():
            method = cls.__dict__[operation]
            if (
                callable(method)
                and not getattr(method, "__isabstractmethod__", False)
                and not getattr(method, "_mdh_observed", False)
            ):
                setattr(cls, operation, _observed(method))


class BasePriceProvider(_ObservedProvider):
    name = "none"
    # Instrument types the hub has implemented a native mapping for. These describe
    # code, never the user's subscription (see PROVIDER_NOT_ENTITLED for that).
    price_sec_types: frozenset[str] = frozenset({"stock", "etf"})
    price_history_sec_types: frozenset[str] = frozenset({"stock", "etf"})
    # Bar intervals (canonical notation) requested from the provider at exactly that
    # length. Every other canonical interval is derived by PriceService.
    native_intervals: frozenset[str] = frozenset({"1m", "5m", "1d"})

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


class BaseCompanyProvider(_ObservedProvider):
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


class BaseOptionsProvider(_ObservedProvider):
    name = "none"
    option_underlying_sec_types: frozenset[str] = frozenset({"stock", "etf"})

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


class BaseNewsProvider(_ObservedProvider):
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


def _upcoming_unsupported(provider: str) -> CapabilityNotSupportedError:
    return CapabilityNotSupportedError(
        provider, "upcoming earnings", sec_type="stock", supported=[]
    )


class BaseEarningsProvider(_ObservedProvider):
    """Common base of the two earnings interfaces (upcoming dates, reported history)."""

    name = "none"

    def configure(self, config: Any) -> None:
        self._runtime_config = config
        _apply_runtime_config_defaults(self, config)

    @abstractmethod
    async def test_connection(self) -> dict[str, Any]:
        """Test connectivity using the provider's shared request budget."""


class BaseEarningsUpcomingProvider(BaseEarningsProvider):
    """Announced report dates and estimates (capability ``earnings_upcoming``).

    ``upcoming_mode`` is a planner strategy, not a capability: ``calendar`` providers
    answer one market-wide request for a date range, ``symbol`` providers answer one
    request per stock and may offer a one-day market calendar.
    """

    upcoming_mode: Literal["calendar", "symbol"] = "calendar"
    earnings_day_calendar = False

    async def get_upcoming_earnings(
        self, start: date, end: date, roots: list[str] | None
    ) -> list[EarningsEvent]:
        """Calendar mode: fetch the calendar once for the range; None roots requests all symbols."""
        raise _upcoming_unsupported(self.name)

    async def get_symbol_earnings(self, root: str) -> list[EarningsEvent]:
        """Symbol mode: upcoming and reported events of one stock in one request."""
        raise _upcoming_unsupported(self.name)

    async def get_earnings_for_date(self, day: date) -> list[EarningsEvent]:
        """Day calendar: all events of the market on one date."""
        raise _upcoming_unsupported(self.name)


class BaseEarningsHistoryProvider(BaseEarningsProvider):
    """Reported quarters of one stock (capability ``earnings_history``)."""

    @abstractmethod
    async def get_earnings_history(self, root: str) -> list[EarningsEvent]:
        """Fetch reported events for one stock."""


class BaseVolatilityProvider(_ObservedProvider):
    """Underlying implied volatility, separate from per-contract options data."""

    name = "none"
    volatility_sec_types: frozenset[str] = frozenset()
    volatility_history_sec_types: frozenset[str] = frozenset()
    volatility_tenors: frozenset[int] = frozenset()

    def configure(self, config: Any) -> None:
        """Apply runtime configuration from the admin repository."""
        self._runtime_config = config
        _apply_runtime_config_defaults(self, config)

    @abstractmethod
    async def get_implied_volatility(
        self,
        symbol: str,
        sec_type: VolatilitySecType = "stock",
        ric: str | None = None,
    ) -> VolatilitySnapshot:
        """Fetch an underlying IV snapshot, in decimal fractions."""

    @abstractmethod
    async def get_implied_volatility_history(
        self,
        symbol: str,
        start: date,
        end: date,
        tenor_days: VolatilityTenorDays = 30,
        sec_type: VolatilitySecType = "stock",
        ric: str | None = None,
    ) -> VolatilityHistory:
        """Fetch daily underlying IV points, in decimal fractions."""

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
