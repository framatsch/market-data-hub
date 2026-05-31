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

def test_map_interval_all(ibkr_provider):
    assert ibkr_provider._map_interval("1m") == "1 min"
    assert ibkr_provider._map_interval("5m") == "5 mins"
    assert ibkr_provider._map_interval("15m") == "15 mins"
    assert ibkr_provider._map_interval("1h") == "1 hour"
    assert ibkr_provider._map_interval("1d") == "1 day"
    assert ibkr_provider._map_interval("unknown") == "1 day"

def test_create_contract_types(ibkr_provider):
    with patch("app.providers.ibkr.Stock") as mock_stock:
        ibkr_provider._create_contract("AAPL", sec_type="stock")
        mock_stock.assert_called()

    with patch("app.providers.ibkr.Index") as mock_index:
        ibkr_provider._create_contract("SPX", sec_type="index")
        mock_index.assert_called()

def test_create_contract_future(ibkr_provider):
    with patch("app.providers.ibkr.Future") as mock_future:
        ibkr_provider._create_contract("ES", sec_type="future")
        mock_future.assert_called()



def test_create_contract_indices(ibkr_provider):
    with patch("app.providers.ibkr.Index") as mock_index:
        ibkr_provider._create_contract("^SPX", sec_type="index")
        # Should strip ^
        mock_index.assert_called_with("SPX", "CBOE")
        
        ibkr_provider._create_contract("INDU", sec_type="index")
        mock_index.assert_called_with("INDU", "NYSE")
