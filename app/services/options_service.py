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
from typing import Any, Literal

import structlog

from app.models.options import OptionChain, OptionQuote
from app.providers.registry import get_registry


class OptionsService:
    def __init__(self, registry: Any = None) -> None:
        self.registry = registry or get_registry()

    async def get_option_chain(
        self,
        symbol: str,
        expiry: date,
        provider_name: str | None = None,
        min_strike: Decimal | None = None,
        max_strike: Decimal | None = None,
        right: Literal["call", "put"] | None = None,
        market_data_type: int | None = None
    ) -> OptionChain:
        provider = self.registry.get_options_provider(provider_name)
        structlog.contextvars.bind_contextvars(provider=provider.name)
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
        provider_name: str | None = None,
        market_data_type: int | None = None
    ) -> OptionQuote:
        provider = self.registry.get_options_provider(provider_name)
        structlog.contextvars.bind_contextvars(provider=provider.name)
        return await provider.get_option_quote(symbol, option_id, market_data_type=market_data_type)

options_service = OptionsService()
