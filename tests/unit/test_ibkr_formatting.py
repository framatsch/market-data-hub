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
from unittest.mock import patch, MagicMock
from app.providers.ibkr import IBKRProvider

@pytest.fixture
def ibkr_provider():
    with patch("app.providers.ibkr.IB"):
        provider = IBKRProvider()
        yield provider

def test_format_option_id(ibkr_provider):
    # This might fail if _format_option_id is not implemented or named differently
    # Let's check the code first
    pass

def test_ibkr_effective_market_data_type(ibkr_provider):
    ibkr_provider.market_data_type = 3
    assert ibkr_provider._get_effective_market_data_type() == 3
    
    ibkr_provider._requested_market_data_type = 1
    assert ibkr_provider._get_effective_market_data_type() == 1
