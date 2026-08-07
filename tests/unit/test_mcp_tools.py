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

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.mcp import (
    _tool_get_company_profile,
    _tool_get_historical_prices,
    _tool_get_last_price,
    _tool_get_market_status,
    _tool_get_option_chain,
    _tool_get_option_quote,
)
from app.models.common import MarketStatus
from app.models.company import CompanyProfile
from app.models.options import OptionChain, OptionQuote
from app.models.price import PriceBar, PriceQuote


@pytest.mark.asyncio
async def test_tool_get_last_price():
    with patch("app.api.mcp._price_service") as mock_service_factory:
        mock_service = MagicMock()
        mock_service.get_latest_price = AsyncMock(return_value=PriceQuote(
            symbol="AAPL", price=Decimal("150.00"), currency="USD", 
            timestamp=datetime.now(), provider="test"
        ))
        mock_service_factory.return_value = mock_service
        
        result = await _tool_get_last_price({"symbol": "AAPL"})
        assert "AAPL" in result["content"][0]["text"]

@pytest.mark.asyncio
async def test_tool_get_historical_prices():
    with patch("app.api.mcp._price_service") as mock_service_factory:
        mock_service = MagicMock()
        mock_service.get_historical_prices = AsyncMock(return_value=[
            PriceBar(symbol="AAPL", start=datetime.now(), end=datetime.now(), 
                     open=Decimal("149.00"), high=Decimal("151.00"), 
                     low=Decimal("148.00"), close=Decimal("150.00"), 
                     volume=1000, provider="test")
        ])
        mock_service_factory.return_value = mock_service
        
        result = await _tool_get_historical_prices({
            "symbol": "AAPL", "interval": "1d", 
            "start_date": "2024-01-01", "end_date": "2024-01-02"
        })
        assert "AAPL" in result["content"][0]["text"]

@pytest.mark.asyncio
async def test_tool_get_option_chain():
    with patch("app.api.mcp._options_service") as mock_service_factory:
        mock_service = MagicMock()
        mock_service.get_option_chain = AsyncMock(return_value=OptionChain(
            underlying_symbol="AAPL", expiry=date(2024, 1, 19), options=[], provider="test"
        ))
        mock_service_factory.return_value = mock_service
        
        result = await _tool_get_option_chain({"symbol": "AAPL", "expiry": "2024-01-19"})
        assert "AAPL" in result["content"][0]["text"]

@pytest.mark.asyncio
async def test_tool_get_option_quote():
    with patch("app.api.mcp._options_service") as mock_service_factory:
        mock_service = MagicMock()
        mock_service.get_option_quote = AsyncMock(return_value=OptionQuote(
            symbol="AAPL240119C00150000", underlying_symbol="AAPL", strike=Decimal(150), 
            expiry=date(2024, 1, 19), type="call", price=Decimal("5.00"), 
            currency="USD", provider="test"
        ))
        mock_service_factory.return_value = mock_service
        
        result = await _tool_get_option_quote({"symbol": "AAPL", "option_id": "AAPL240119C00150000"})
        assert "AAPL240119C00150000" in result["content"][0]["text"]

@pytest.mark.asyncio
async def test_tool_get_company_profile():
    with patch("app.api.mcp._company_service") as mock_service_factory:
        mock_service = MagicMock()
        mock_service.get_company_profile = AsyncMock(return_value=CompanyProfile(
            symbol="AAPL", name="Apple Inc.", exchange="NASDAQ", currency="USD", provider="test"
        ))
        mock_service_factory.return_value = mock_service
        
        result = await _tool_get_company_profile({"symbol": "AAPL"})
        assert "Apple" in result["content"][0]["text"]

@pytest.mark.asyncio
async def test_tool_get_market_status():
    with patch("app.api.mcp._price_service") as mock_service_factory:
        mock_service = MagicMock()
        mock_service.get_market_status = AsyncMock(return_value=MarketStatus(
            market="open", server_time=datetime.now(), provider="test"
        ))
        mock_service_factory.return_value = mock_service
        
        result = await _tool_get_market_status({"provider": "test"})
        assert "open" in result["content"][0]["text"]

@pytest.mark.asyncio
async def test_tool_get_last_price_not_found():
    with patch("app.api.mcp._price_service") as mock_service_factory:
        mock_service = MagicMock()
        mock_service.get_latest_price = AsyncMock(return_value=None)
        mock_service_factory.return_value = mock_service
        
        result = await _tool_get_last_price({"symbol": "AAPL"})
        assert "No price data found" in result["content"][0]["text"]

@pytest.mark.asyncio
async def test_tool_get_historical_prices_empty():
    with patch("app.api.mcp._price_service") as mock_service_factory:
        mock_service = MagicMock()
        mock_service.get_historical_prices = AsyncMock(return_value=[])
        mock_service_factory.return_value = mock_service
        
        result = await _tool_get_historical_prices({
            "symbol": "AAPL", "interval": "1d", 
            "start_date": "2024-01-01", "end_date": "2024-01-02"
        })
        assert "No historical data found" in result["content"][0]["text"]

@pytest.mark.asyncio
async def test_tool_get_option_chain_empty():
    with patch("app.api.mcp._options_service") as mock_service_factory:
        mock_service = MagicMock()
        mock_service.get_option_chain = AsyncMock(return_value=OptionChain(
            underlying_symbol="AAPL", expiry=date(2024, 1, 19), options=[], provider="test"
        ))
        mock_service_factory.return_value = mock_service
        
        result = await _tool_get_option_chain({"symbol": "AAPL", "expiry": "2024-01-19"})
        assert "[]" in result["content"][0]["text"]
