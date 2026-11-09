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

from datetime import UTC, datetime

import structlog

from app.models.common import MarketStatus
from app.models.price import PriceBar, PriceQuote
from app.providers.base import BasePriceProvider
from app.providers.registry import ProviderRegistry, get_registry
from app.utils.errors import CapabilityNotSupportedError
from app.utils.symbols import ParsedSymbol


def _as_utc(value: datetime) -> datetime:
    """Interpret legacy naive request dates as UTC; preserve aware instants."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _check_support(
    provider: BasePriceProvider, operation: str, symbol: ParsedSymbol
) -> None:
    """501 before any provider call when the hub has no mapping for this type."""
    supported = (
        provider.price_sec_types
        if operation == "last"
        else provider.price_history_sec_types
    )
    if symbol.sec_type not in supported:
        raise CapabilityNotSupportedError(
            provider.name,
            operation,
            sec_type=symbol.sec_type,
            supported=sorted(supported),
        )


class PriceService:
    def __init__(self, registry: ProviderRegistry | None = None) -> None:
        self.registry = registry or get_registry()

    async def get_latest_price(
        self,
        symbol: ParsedSymbol,
        provider_name: str | None = None,
        market_data_type: int | None = None,
    ) -> PriceQuote:
        async with self.registry.use_price_provider(provider_name) as provider:
            structlog.contextvars.bind_contextvars(provider=provider.name)
            _check_support(provider, "last", symbol)
            quote = await provider.get_last_price(
                symbol.root, market_data_type, symbol.sec_type
            )
            return quote.model_copy(update={"symbol": symbol.canonical})

    async def get_historical_prices(
        self,
        symbol: ParsedSymbol,
        interval: str,
        start: datetime,
        end: datetime,
        extended_hours: bool = False,
        provider_name: str | None = None,
    ) -> list[PriceBar]:
        start, end = _as_utc(start), _as_utc(end)
        async with self.registry.use_price_provider(provider_name) as provider:
            structlog.contextvars.bind_contextvars(provider=provider.name)
            _check_support(provider, "history", symbol)
            bars = await provider.get_historical_prices(
                symbol.root,
                interval,
                start,
                end,
                extended_hours,
                sec_type=symbol.sec_type,
            )
            return [bar.model_copy(update={"symbol": symbol.canonical}) for bar in bars]

    async def get_market_status(self, provider_name: str | None = None) -> MarketStatus:
        async with self.registry.use_price_provider(provider_name) as provider:
            structlog.contextvars.bind_contextvars(provider=provider.name)
            return await provider.get_market_status()


price_service = PriceService()
