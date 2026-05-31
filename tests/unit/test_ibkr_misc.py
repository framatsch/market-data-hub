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

def test_ibkr_market_data_type_logic(ibkr_provider):
    ibkr_provider.market_data_type = 3
    assert ibkr_provider._get_effective_market_data_type() == 3
    
    # Explicit override
    ibkr_provider._requested_market_data_type = 1
    assert ibkr_provider._get_effective_market_data_type() == 1
    
def test_ibkr_calculate_duration_logic(ibkr_provider):
    from datetime import datetime, timedelta
    now = datetime.now()
    # 2 years -> 3 Y
    assert "3 Y" in ibkr_provider._calculate_duration(now - timedelta(days=731), now)
    # 6 months -> 7 M
    assert "7 M" in ibkr_provider._calculate_duration(now - timedelta(days=180), now)
    # 7 days -> 8 D
    assert "8 D" in ibkr_provider._calculate_duration(now - timedelta(days=7), now)
    # 2 days -> 3 D
    assert "3 D" in ibkr_provider._calculate_duration(now - timedelta(days=2), now)

def test_ibkr_is_valid_nan(ibkr_provider):
    import math
    assert ibkr_provider._is_valid(float('nan')) is False
    assert ibkr_provider._is_valid(None) is False
    assert ibkr_provider._is_valid(10.0) is True

def test_on_ib_error_no_crash(ibkr_provider):
    # Verify it handles various error codes without crashing
    ibkr_provider._on_ib_error(1, 2104, "Market data farm is connected", None)
    ibkr_provider._on_ib_error(1, 1100, "Connectivity between IB and TWS has been lost", None)


