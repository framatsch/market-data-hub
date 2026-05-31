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
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, date
from decimal import Decimal
from app.providers.ibkr import IBKRProvider

@pytest.fixture
def ibkr_provider():
    with patch("app.providers.ibkr.IB") as mock_ib:
        provider = IBKRProvider()
        yield provider, mock_ib.return_value

@pytest.mark.asyncio
async def test_get_historical_prices_ibkr(ibkr_provider):
    provider, mock_ib = ibkr_provider
    provider._ensure_connection = AsyncMock()
    provider._disconnect = AsyncMock()
    
    # Mock return bars
    mock_bar = MagicMock()
    mock_bar.date = date(2024, 1, 1)
    mock_bar.open = 150.0
    mock_bar.high = 155.0
    mock_bar.low = 149.0
    mock_bar.close = 152.0
    mock_bar.volume = 1000000
    
    mock_ib.reqHistoricalDataAsync = AsyncMock(return_value=[mock_bar])
    
    result = await provider.get_historical_prices("AAPL", "1d", datetime.now(), datetime.now())
    
    assert len(result) == 1
    assert result[0].close == Decimal("152.0")
    assert result[0].provider == "ibkr"
