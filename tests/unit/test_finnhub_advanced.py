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
import httpx
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import date
from app.providers.finnhub import FinnhubProvider
from app.utils.errors import ProviderError

@pytest.fixture
def finnhub_provider():
    return FinnhubProvider()

@pytest.mark.asyncio
async def test_get_company_news_rate_limit(finnhub_provider):
    # Mock rate limit check to fail
    finnhub_provider._check_rate_limit = AsyncMock(return_value=False)
    
    with pytest.raises(ProviderError) as exc:
        await finnhub_provider.get_company_news("AAPL", date(2024, 1, 1), date(2024, 1, 2))
    assert "rate limit exceeded" in str(exc.value)

@pytest.mark.asyncio
async def test_get_company_news_api_error(finnhub_provider):
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    
    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        with pytest.raises(ProviderError):
            await finnhub_provider.get_company_news("AAPL", date(2024, 1, 1), date(2024, 1, 2))
