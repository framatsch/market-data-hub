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

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.providers.ibkr import IBKRProvider


@pytest.fixture
def ibkr_provider():
    with patch("app.providers.ibkr.IB"):
        provider = IBKRProvider()
        yield provider

def test_map_interval(ibkr_provider):
    from app.utils.errors import ProviderError
    assert ibkr_provider._map_interval("1m") == "1 min"
    assert ibkr_provider._map_interval("1h") == "1 hour"
    assert ibkr_provider._map_interval("1d") == "1 day"
    with pytest.raises(ProviderError) as exc:
        ibkr_provider._map_interval("unknown")
    assert "Unsupported interval 'unknown'" in str(exc.value)

def test_calculate_duration(ibkr_provider):
    now = datetime.now()
    # Implementation adds 1 to the diff
    assert "2 D" in ibkr_provider._calculate_duration(now - timedelta(days=1), now)
    # 900 days is approx 2.5 years, current impl returns years + 1 = 3 Y
    assert "3 Y" in ibkr_provider._calculate_duration(now - timedelta(days=900), now)
    assert "2 Y" in ibkr_provider._calculate_duration(now - timedelta(days=365), now)

def test_create_contract(ibkr_provider):
    with patch("app.providers.ibkr.Stock") as mock_stock:
        ibkr_provider._create_contract("AAPL")
        mock_stock.assert_called_with("AAPL", "SMART", "USD")

    with patch("app.providers.ibkr.Index") as mock_index:
        ibkr_provider._create_contract("SPX", sec_type="index")
        mock_index.assert_called_with("SPX", "CBOE")

def test_get_index_exchange(ibkr_provider):
    assert ibkr_provider._get_index_exchange("SPX") == "CBOE"
    assert ibkr_provider._get_index_exchange("NDX") == "NASDAQ"
    assert ibkr_provider._get_index_exchange("INDU") == "NYSE"
    assert ibkr_provider._get_index_exchange("UNKNOWN") == "CBOE"
