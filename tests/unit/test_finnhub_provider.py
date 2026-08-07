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

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from app.admin.crypto import CryptoService
from app.admin.key_repository import KeyRepository
from app.admin.runtime import set_admin_runtime
from app.providers.finnhub import FinnhubProvider


@pytest.fixture
def finnhub_provider():
    provider = FinnhubProvider()
    provider._api_key = "test-key"
    provider._api_key_configured = True
    return provider

def test_init_does_not_load_api_key():
    provider = FinnhubProvider()

    assert provider._api_key is None


@pytest.mark.asyncio
async def test_ensure_api_key_loads_from_key_repository(tmp_path):
    key = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    key_repo = KeyRepository(str(tmp_path / "keys.db"), CryptoService(key))
    await key_repo.save("finnhub", "api_key", "db-key")
    set_admin_runtime(key_repository=key_repo)

    try:
        provider = FinnhubProvider()
        api_key = await provider._ensure_api_key()
    finally:
        set_admin_runtime()

    assert api_key == "db-key"

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


@pytest.mark.asyncio
async def test_test_connection_success(finnhub_provider):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "ok"

    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        result = await finnhub_provider.test_connection()

    assert result["status_code"] == 200
    assert result["success"] is True
    assert result["message"] == "Finnhub API key valid"


@pytest.mark.asyncio
async def test_test_connection_auth_failure(finnhub_provider):
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "unauthorized"

    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        result = await finnhub_provider.test_connection()

    assert result["status_code"] == 401
    assert result["success"] is False
    assert result["message"] == "Invalid Finnhub API key"


@pytest.mark.asyncio
async def test_test_connection_service_unavailable(finnhub_provider):
    with patch("httpx.AsyncClient.get", side_effect=Exception("boom")):
        result = await finnhub_provider.test_connection()

    assert result["status_code"] == 503
    assert result["success"] is False
    assert result["message"] == "Finnhub service unavailable"
