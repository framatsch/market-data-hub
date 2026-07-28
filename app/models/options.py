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

from pydantic import BaseModel


class OptionQuote(BaseModel):
    symbol: str
    underlying_symbol: str
    strike: Decimal
    expiry: date
    type: Literal["call", "put"]
    price: Decimal
    bid: Decimal | None = None
    ask: Decimal | None = None
    volume: int | None = None
    open_interest: int | None = None
    implied_volatility: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    provider: str

class OptionChain(BaseModel):
    underlying_symbol: str
    expiry: date
    options: list[OptionQuote]
    provider: str
