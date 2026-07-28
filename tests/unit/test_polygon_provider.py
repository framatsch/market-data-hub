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
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, date
from decimal import Decimal
import httpx

from app.providers.polygon import PolygonProvider
from app.models.price import PriceQuote, PriceBar
from app.utils.errors import DataNotFoundError

@pytest.fixture
def polygon_provider():
    with patch("app.providers.polygon.httpx.AsyncClient") as mock_client:
        mock_instance = mock_client.return_value
        mock_instance.get = AsyncMock()
        provider = PolygonProvider()
        provider.api_key = "test-polygon-key"
        yield provider

def test_format_ticker(polygon_provider):
    assert polygon_provider._format_ticker("AAPL", "stock") == "AAPL"
    assert polygon_provider._format_ticker("aapl", "stock") == "AAPL"
    assert polygon_provider._format_ticker("AAPL240119C00150000", "option") == "O:AAPL240119C00150000"
    assert polygon_provider._format_ticker("O:AAPL240119C00150000", "option") == "O:AAPL240119C00150000"

@pytest.mark.asyncio
async def test_get_last_price_success(polygon_provider):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": {"p": 150.00, "b": 149.90, "a": 150.10, "t": 1609459200000000000}
    }
    polygon_provider._client.get.return_value = mock_resp
    
    result = await polygon_provider.get_last_price("AAPL")
    
    assert result.symbol == "AAPL"
    assert result.price == Decimal("150.0")
    assert result.provider == "polygon"


@pytest.mark.asyncio
async def test_test_connection_success(polygon_provider):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "ok"
    polygon_provider._client.get.return_value = mock_resp

    result = await polygon_provider.test_connection()

    assert result["status_code"] == 200
    assert result["success"] is True
    assert result["message"] == "Polygon API key valid"


@pytest.mark.asyncio
async def test_test_connection_auth_failure(polygon_provider):
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = "forbidden"
    polygon_provider._client.get.return_value = mock_resp

    result = await polygon_provider.test_connection()

    assert result["status_code"] == 401
    assert result["success"] is False
    assert result["message"] == "Invalid Polygon API key"


@pytest.mark.asyncio
async def test_test_connection_service_unavailable(polygon_provider):
    polygon_provider._client.get.side_effect = Exception("down")

    result = await polygon_provider.test_connection()

    assert result["status_code"] == 503
    assert result["success"] is False
    assert result["message"] == "Polygon service unavailable"

@pytest.mark.asyncio
async def test_get_last_price_404(polygon_provider):
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    polygon_provider._client.get.return_value = mock_resp
    
    from app.utils.errors import DataNotFoundError
    with pytest.raises(DataNotFoundError):
        await polygon_provider.get_last_price("UNKNOWN")

@pytest.mark.asyncio
async def test_get_last_price_fallback(polygon_provider):
    # Mock 403 then success on fallback
    mock_403 = MagicMock()
    mock_403.status_code = 403
    
    mock_fallback = MagicMock()
    mock_fallback.status_code = 200
    mock_fallback.json.return_value = {
        "results": [{"c": 148.00, "t": 1609459200000}]
    }
    
    polygon_provider._client.get.side_effect = [mock_403, mock_fallback]
    
    result = await polygon_provider.get_last_price("AAPL")
    
    assert result.price == Decimal("148.0")
    assert "delayed/prev" in result.provider



@pytest.mark.asyncio
async def test_get_market_status(polygon_provider):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "market": "open",
        "serverTime": "2024-01-01T12:00:00Z"
    }
    polygon_provider._client.get.return_value = mock_resp
    
    status = await polygon_provider.get_market_status()
    assert status.market == "open"
    assert status.provider == "polygon"

@pytest.mark.asyncio
async def test_get_company_profile(polygon_provider):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": {
            "ticker": "AAPL",
            "name": "Apple Inc.",
            "primary_exchange": "NASDAQ",
            "currency_name": "usd"
        }
    }
    polygon_provider._client.get.return_value = mock_resp
    
    profile = await polygon_provider.get_company_profile("AAPL")
    assert profile.symbol == "AAPL"
    assert profile.name == "Apple Inc."
    assert profile.currency == "USD"

@pytest.mark.asyncio
async def test_search_companies(polygon_provider):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": [{"ticker": "AAPL", "name": "Apple Inc.", "primary_exchange": "NASDAQ"}]
    }
    polygon_provider._client.get.return_value = mock_resp
    
    results = await polygon_provider.search_companies("Apple")
    assert len(results) == 1
    assert results[0].symbol == "AAPL"

@pytest.mark.asyncio
async def test_get_historical_prices_error(polygon_provider):
    polygon_provider._client.get.side_effect = Exception("Aggs Fail")
    from app.utils.errors import ProviderError
    with pytest.raises(ProviderError):
        await polygon_provider.get_historical_prices("AAPL", "1d", datetime.now(), datetime.now())

@pytest.mark.asyncio
async def test_get_historical_prices(polygon_provider):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": [{"o": 150, "h": 155, "l": 149, "c": 152, "v": 1000000, "t": 1609459200000}]
    }
    polygon_provider._client.get.return_value = mock_resp
    
    bars = await polygon_provider.get_historical_prices("AAPL", "1d", datetime.now(), datetime.now())
    assert len(bars) == 1
    assert bars[0].close == Decimal("152.0")



@pytest.mark.asyncio
async def test_search_companies_error(polygon_provider):
    polygon_provider._client.get.side_effect = Exception("API Down")
    from app.utils.errors import ProviderError
    with pytest.raises(ProviderError):
        await polygon_provider.search_companies("Apple")

@pytest.mark.asyncio
async def test_get_option_chain(polygon_provider):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": [{
            "ticker": "O:AAPL240119C00150000",
            "details": {"strike_price": 150, "expiration_date": "2024-01-19", "contract_type": "call"},
            "last_quote": {"bid": 5.0, "ask": 5.1}
        }]
    }
    polygon_provider._client.get.return_value = mock_resp
    
    chain = await polygon_provider.get_option_chain("AAPL", date(2024, 1, 19))
    assert chain.underlying_symbol == "AAPL"
    assert len(chain.options) == 1
    assert chain.options[0].symbol == "O:AAPL240119C00150000"

@pytest.mark.asyncio
async def test_polygon_filter_rth(polygon_provider):
    from zoneinfo import ZoneInfo
    
    tz = ZoneInfo("America/New_York")
    
    # 09:29 ET (Pre-market)
    pre_market = datetime(2024, 1, 10, 9, 29, tzinfo=tz) 
    # 09:30 ET (Open)
    market_open = datetime(2024, 1, 10, 9, 30, tzinfo=tz)
    # 15:59 ET (Just before close)
    market_close = datetime(2024, 1, 10, 15, 59, tzinfo=tz)
    # 16:00 ET (After-hours)
    after_hours = datetime(2024, 1, 10, 16, 0, tzinfo=tz)
    # Saturday (Closed)
    weekend = datetime(2024, 1, 13, 10, 0, tzinfo=tz)

    bars = [
        PriceBar(symbol="AAPL", start=pre_market, end=pre_market, open=Decimal(1), high=Decimal(1), low=Decimal(1), close=Decimal(1), volume=100, provider="polygon"),
        PriceBar(symbol="AAPL", start=market_open, end=market_open, open=Decimal(1), high=Decimal(1), low=Decimal(1), close=Decimal(1), volume=100, provider="polygon"),
        PriceBar(symbol="AAPL", start=market_close, end=market_close, open=Decimal(1), high=Decimal(1), low=Decimal(1), close=Decimal(1), volume=100, provider="polygon"),
        PriceBar(symbol="AAPL", start=after_hours, end=after_hours, open=Decimal(1), high=Decimal(1), low=Decimal(1), close=Decimal(1), volume=100, provider="polygon"),
        PriceBar(symbol="AAPL", start=weekend, end=weekend, open=Decimal(1), high=Decimal(1), low=Decimal(1), close=Decimal(1), volume=100, provider="polygon"),
    ]

    filtered = polygon_provider._filter_rth(bars)
    
    assert len(filtered) == 2
    assert filtered[0].start == market_open
    assert filtered[1].start == market_close

@pytest.mark.asyncio
async def test_get_historical_prices_intraday_filtering(polygon_provider):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("America/New_York")
    # 09:29 ET
    t_pre = int(datetime(2024, 1, 10, 9, 29, tzinfo=tz).timestamp() * 1000)
    # 09:30 ET
    t_open = int(datetime(2024, 1, 10, 9, 30, tzinfo=tz).timestamp() * 1000)
    
    mock_resp.json.return_value = {
        "results": [
            {"o": 150, "h": 155, "l": 149, "c": 152, "v": 100, "t": t_pre},
            {"o": 150, "h": 155, "l": 149, "c": 152, "v": 100, "t": t_open},
        ]
    }
    polygon_provider._client.get.return_value = mock_resp
    
    # RTH only (default)
    bars_rth = await polygon_provider.get_historical_prices("AAPL", "5m", datetime.now(), datetime.now())
    assert len(bars_rth) == 1
    
    # Extended hours
    bars_ext = await polygon_provider.get_historical_prices("AAPL", "5m", datetime.now(), datetime.now(), extended_hours=True)
    assert len(bars_ext) == 2
