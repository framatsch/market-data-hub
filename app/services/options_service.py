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

from datetime import date
from decimal import Decimal
from typing import Literal

import structlog

from app.models.options import OptionChain, OptionQuote
from app.providers.base import BaseOptionsProvider
from app.providers.registry import ProviderRegistry, get_registry
from app.utils.errors import CapabilityNotSupportedError
from app.utils.symbols import ParsedSymbol


def _check_support(
    provider: BaseOptionsProvider, operation: str, symbol: ParsedSymbol
) -> None:
    """501 before any provider call when the underlying type has no mapping."""
    supported = provider.option_underlying_sec_types
    if symbol.sec_type not in supported:
        raise CapabilityNotSupportedError(
            provider.name,
            operation,
            sec_type=symbol.sec_type,
            supported=sorted(supported),
        )


def _type_kwargs(symbol: ParsedSymbol) -> dict[str, str]:
    """Stocks and ETFs use the provider default; only other types are passed."""
    return {} if symbol.sec_type in ("stock", "etf") else {"sec_type": symbol.sec_type}


class OptionsService:
    def __init__(self, registry: ProviderRegistry | None = None) -> None:
        self.registry = registry or get_registry()

    async def get_option_chain(
        self,
        symbol: ParsedSymbol,
        expiry: date,
        provider_name: str | None = None,
        min_strike: Decimal | None = None,
        max_strike: Decimal | None = None,
        right: Literal["call", "put"] | None = None,
        market_data_type: int | None = None,
    ) -> OptionChain:
        async with self.registry.use_options_provider(provider_name) as provider:
            structlog.contextvars.bind_contextvars(provider=provider.name)
            _check_support(provider, "option_chain", symbol)
            chain = await provider.get_option_chain(
                symbol.root,
                expiry,
                min_strike=min_strike,
                max_strike=max_strike,
                right=right,
                market_data_type=market_data_type,
                **_type_kwargs(symbol),
            )
            return chain.model_copy(
                update={
                    "underlying_symbol": symbol.canonical,
                    "options": [
                        option.model_copy(
                            update={"underlying_symbol": symbol.canonical}
                        )
                        for option in chain.options
                    ],
                }
            )

    async def get_option_quote(
        self,
        symbol: ParsedSymbol,
        option_id: str,
        provider_name: str | None = None,
        market_data_type: int | None = None,
    ) -> OptionQuote:
        async with self.registry.use_options_provider(provider_name) as provider:
            structlog.contextvars.bind_contextvars(provider=provider.name)
            _check_support(provider, "option_quote", symbol)
            quote = await provider.get_option_quote(
                symbol.root,
                option_id,
                market_data_type=market_data_type,
                **_type_kwargs(symbol),
            )
            return quote.model_copy(update={"underlying_symbol": symbol.canonical})


options_service = OptionsService()
