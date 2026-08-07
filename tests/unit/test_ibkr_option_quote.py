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

from unittest.mock import MagicMock, patch

import pytest

from app.providers.ibkr import IBKRProvider


@pytest.fixture
def ibkr_provider():
    with patch("app.providers.ibkr.IB") as mock_ib:
        provider = IBKRProvider()
        yield provider, mock_ib.return_value

def test_extract_greeks_none(ibkr_provider):
    provider, _ = ibkr_provider
    ticker = MagicMock()
    ticker.modelGreeks = None
    
    greeks = provider._extract_greeks(ticker)
    assert greeks["delta"] is None
    assert greeks["implied_volatility"] is None
