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

from datetime import datetime

import structlog

from app.models.common import MarketStatus
from app.models.price import PriceBar, PriceQuote
from app.providers.registry import ProviderRegistry, get_registry


class PriceService:
    def __init__(self, registry: ProviderRegistry | None = None) -> None:
        self.registry = registry or get_registry()

    async def get_latest_price(
        self,
        symbol: str,
        provider_name: str | None = None,
        market_data_type: int | None = None,
        sec_type: str = "stock",
    ) -> PriceQuote:
        async with self.registry.use_price_provider(provider_name) as provider:
            structlog.contextvars.bind_contextvars(provider=provider.name)
            return await provider.get_last_price(symbol, market_data_type, sec_type)

    async def get_historical_prices(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
        extended_hours: bool = False,
        provider_name: str | None = None,
        sec_type: str = "STK",
    ) -> list[PriceBar]:
        async with self.registry.use_price_provider(provider_name) as provider:
            structlog.contextvars.bind_contextvars(provider=provider.name)
            return await provider.get_historical_prices(
                symbol, interval, start, end, extended_hours, sec_type=sec_type
            )

    async def get_market_status(self, provider_name: str | None = None) -> MarketStatus:
        async with self.registry.use_price_provider(provider_name) as provider:
            structlog.contextvars.bind_contextvars(provider=provider.name)
            return await provider.get_market_status()


price_service = PriceService()
