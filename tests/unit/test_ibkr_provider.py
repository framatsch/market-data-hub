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

import pytest
import math
from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.providers.ibkr import IBKRProvider

@pytest.fixture
def ibkr_provider():
    with patch("app.providers.ibkr.IB"):
        provider = IBKRProvider()
        return provider

def test_ibkr_is_valid(ibkr_provider):
    assert ibkr_provider._is_valid(10.5) is True
    assert ibkr_provider._is_valid(None) is False
    assert ibkr_provider._is_valid(float('nan')) is False

def test_ibkr_to_decimal(ibkr_provider):
    assert ibkr_provider._to_decimal(10.5) == Decimal("10.5")
    assert ibkr_provider._to_decimal(None) is None
    assert ibkr_provider._to_decimal(float('nan')) is None

def test_extract_greeks(ibkr_provider):
    ticker = MagicMock()
    ticker.modelGreeks = MagicMock()
    ticker.modelGreeks.delta = 0.5
    ticker.modelGreeks.gamma = 0.1
    ticker.modelGreeks.theta = -0.05
    ticker.modelGreeks.vega = 0.2
    ticker.modelGreeks.impliedVol = 0.3
    
    greeks = ibkr_provider._extract_greeks(ticker)
    assert greeks["delta"] == Decimal("0.5")
    assert greeks["implied_volatility"] == Decimal("0.3")

def test_extract_greeks_missing(ibkr_provider):
    ticker = MagicMock()
    ticker.modelGreeks = None
    
    greeks = ibkr_provider._extract_greeks(ticker)
    assert greeks["delta"] is None
    assert greeks["implied_volatility"] is None
