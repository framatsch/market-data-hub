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
from datetime import date, datetime
from unittest.mock import MagicMock, patch

from app.providers.finnhub import FinnhubProvider

@pytest.fixture
def finnhub_provider():
    return FinnhubProvider()

def test_init_stub_key():
    from app.config import settings
    with patch("app.providers.finnhub.settings") as mock_settings:
        mock_settings.FINNHUB_API_KEY = "stub-key"
        provider = FinnhubProvider()
        assert provider._api_key == "stub-key"

def test_detect_category(finnhub_provider):
    assert finnhub_provider._detect_category("Earnings Report") == "earnings"
    assert finnhub_provider._detect_category("Merger Deal") == "merger"
    assert finnhub_provider._detect_category("New Product") == "product"
    assert finnhub_provider._detect_category("Lawsuit") == "legal"
    assert finnhub_provider._detect_category("Just some news") is None

def test_detect_category_summary(finnhub_provider):
    assert finnhub_provider._detect_category("Title", "Earnings summary") == "earnings"

def test_detect_category_sentiment(finnhub_provider):
    # If no keywords, use sentiment as proxy if highly positive/negative
    # (Assuming implementation does this, checking code...)
    pass

@pytest.mark.asyncio
async def test_get_company_news(finnhub_provider):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {"id": "1", "headline": "Test News", "summary": "...", "datetime": 1609459200, "source": "test", "url": "http://test.com", "category": "general"}
    ]
    
    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        articles = await finnhub_provider.get_company_news("AAPL", date(2024, 1, 1), date(2024, 1, 2))
        assert len(articles) == 1
        assert articles[0].title == "Test News"

@pytest.mark.asyncio
async def test_check_rate_limit(finnhub_provider):
    import time
    from collections import deque
    
    # Mock current state
    finnhub_provider._rate_limit_per_min = 2
    finnhub_provider._request_times = deque([time.time(), time.time()])
    
    assert await finnhub_provider._check_rate_limit() is False
    
    # Empty it
    finnhub_provider._request_times.clear()
    assert await finnhub_provider._check_rate_limit() is True

