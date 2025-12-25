from abc import ABC, abstractmethod
from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional

from app.models.price import PriceBar, PriceQuote
from app.models.company import CompanyProfile, CompanySummary
from app.models.options import OptionChain, OptionQuote

class BasePriceProvider(ABC):
    @abstractmethod
    async def get_historical_prices(self, symbol: str, interval: str, start: datetime, end: datetime) -> List[PriceBar]:
        """Fetch historical price bars."""
        pass

    @abstractmethod
    async def get_last_price(self, symbol: str) -> PriceQuote:
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
        include_level2: bool = False
    ) -> OptionChain:
        """Fetch option chain for a given expiry."""
        pass

    @abstractmethod
    async def get_option_quote(self, symbol: str, option_id: str, include_level2: bool = False) -> OptionQuote:
        """Fetch specific option quote."""
        pass
