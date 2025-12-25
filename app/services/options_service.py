from decimal import Decimal
from typing import Literal, Optional
from datetime import date

from app.models.options import OptionChain, OptionQuote
from app.providers.registry import get_registry

class OptionsService:
    def __init__(self, registry=None):
        self.registry = registry or get_registry()

    async def get_option_chain(
        self,
        symbol: str,
        expiry: date,
        provider_name: Optional[str] = None,
        min_strike: Optional[Decimal] = None,
        max_strike: Optional[Decimal] = None,
        right: Optional[Literal["call", "put"]] = None,
        include_level2: bool = False
    ) -> OptionChain:
        provider = self.registry.get_options_provider(provider_name)
        return await provider.get_option_chain(
            symbol, expiry,
            min_strike=min_strike,
            max_strike=max_strike,
            right=right,
            include_level2=include_level2
        )

    async def get_option_quote(
        self,
        symbol: str,
        option_id: str,
        provider_name: Optional[str] = None,
        include_level2: bool = False
    ) -> OptionQuote:
        provider = self.registry.get_options_provider(provider_name)
        return await provider.get_option_quote(symbol, option_id, include_level2=include_level2)

options_service = OptionsService()
