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
from datetime import datetime
from zoneinfo import ZoneInfo
from app.providers.ibkr import IBKRProvider

@pytest.fixture
def ibkr_provider():
    with patch("app.providers.ibkr.IB"):
        provider = IBKRProvider()
        yield provider

def test_is_market_open_new_format(ibkr_provider):
    # Format: "20260122:0400-20260122:2000"
    trading_hours = "20240101:0930-20240101:1600"
    
    with patch("app.providers.ibkr.datetime") as mock_dt:
        mock_now = datetime(2024, 1, 1, 10, 0, tzinfo=ZoneInfo("America/New_York"))
        mock_dt.now.return_value = mock_now
        mock_dt.fromtimestamp = datetime.fromtimestamp
        mock_dt.strftime = datetime.strftime
        
        # Open case
        assert ibkr_provider._is_market_open(trading_hours, "US/Eastern") is True
        
        # Closed case (before)
        mock_dt.now.return_value = datetime(2024, 1, 1, 8, 0, tzinfo=ZoneInfo("America/New_York"))
        assert ibkr_provider._is_market_open(trading_hours, "US/Eastern") is False
        
        # Closed case (after)
        mock_dt.now.return_value = datetime(2024, 1, 1, 17, 0, tzinfo=ZoneInfo("America/New_York"))
        assert ibkr_provider._is_market_open(trading_hours, "US/Eastern") is False

def test_is_market_open_closed_entry(ibkr_provider):
    trading_hours = "20240101:CLOSED"
    with patch("app.providers.ibkr.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2024, 1, 1, 10, 0, tzinfo=ZoneInfo("America/New_York"))
        assert ibkr_provider._is_market_open(trading_hours, "US/Eastern") is False

def test_is_market_open_none(ibkr_provider):
    assert ibkr_provider._is_market_open(None) is None
    assert ibkr_provider._is_market_open("") is None
