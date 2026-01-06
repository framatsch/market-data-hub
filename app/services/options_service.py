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
        market_data_type: Optional[int] = None
    ) -> OptionChain:
        provider = self.registry.get_options_provider(provider_name)
        return await provider.get_option_chain(
            symbol, expiry,
            min_strike=min_strike,
            max_strike=max_strike,
            right=right,
            market_data_type=market_data_type
        )

    async def get_option_quote(
        self,
        symbol: str,
        option_id: str,
        provider_name: Optional[str] = None,
        market_data_type: Optional[int] = None
    ) -> OptionQuote:
        provider = self.registry.get_options_provider(provider_name)
        return await provider.get_option_quote(symbol, option_id, market_data_type=market_data_type)

options_service = OptionsService()
