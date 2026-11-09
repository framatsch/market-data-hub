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


@pytest.mark.asyncio
async def test_future_alias_over_mcp_resolves_to_future():
    from app.utils.symbols import ParsedSymbol

    with patch("app.api.mcp._price_service") as factory:
        service = MagicMock()
        service.get_latest_price = AsyncMock(return_value=PriceQuote(
            symbol="F:ES", price=Decimal(5000), currency="USD",
            timestamp=datetime.now(), provider="test",
        ))
        factory.return_value = service
        result = await _tool_get_last_price({"symbol": "/es", "provider": "ibkr"})
    assert service.get_latest_price.call_args.args[0] == ParsedSymbol("ES", "future")
    assert "F:ES" in result["content"][0]["text"]


@pytest.mark.asyncio
@pytest.mark.parametrize("symbol,sec_type", [("SPX", "INDEX"), ("^SPX", None), ("I:SPX", "index")])
async def test_index_notations_resolve_identically(symbol, sec_type):
    from app.utils.symbols import ParsedSymbol

    with patch("app.api.mcp._price_service") as factory:
        service = MagicMock()
        service.get_latest_price = AsyncMock(return_value=None)
        factory.return_value = service
        args = {"symbol": symbol, **({"sec_type": sec_type} if sec_type else {})}
        await _tool_get_last_price(args)
    assert service.get_latest_price.call_args.args[0] == ParsedSymbol("SPX", "index")


@pytest.mark.asyncio
@pytest.mark.parametrize("args", [
    {"symbol": "F:ES", "sec_type": "stock"},
    {"symbol": ".SPX"},
    {"symbol": "AAPL", "sec_type": "bond"},
])
async def test_invalid_symbol_arguments_raise_validation_error(args):
    from app.utils.errors import DataValidationError

    with patch("app.api.mcp._price_service") as factory:
        with pytest.raises(DataValidationError):
            await _tool_get_last_price(args)
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_company_tools_reject_futures_without_service_call():
    from app.api.mcp import _tool_get_company_news
    from app.utils.errors import DataValidationError

    with patch("app.api.mcp._company_service") as company, patch(
        "app.api.mcp._news_service"
    ) as news:
        for handler in (_tool_get_company_profile, _tool_get_company_news):
            with pytest.raises(DataValidationError):
                await handler({"symbol": "F:ES"})
    company.assert_not_called()
    news.assert_not_called()


@pytest.mark.asyncio
async def test_company_news_goes_through_news_service():
    from app.api.mcp import _tool_get_company_news
    from app.utils.symbols import ParsedSymbol

    with patch("app.api.mcp._news_service") as factory:
        service = MagicMock()
        service.get_company_news = AsyncMock(return_value=[])
        factory.return_value = service
        await _tool_get_company_news({"symbol": "aapl", "provider": "finnhub", "limit": 5})
    args = service.get_company_news.call_args
    assert args.args[0] == ParsedSymbol("AAPL", "stock")
    assert args.kwargs == {"provider_name": "finnhub", "limit": 5}


@pytest.mark.asyncio
async def test_option_tools_underlying_and_option_prefix():
    from app.utils.errors import DataValidationError
    from app.utils.symbols import ParsedSymbol

    with patch("app.api.mcp._options_service") as factory:
        service = MagicMock()
        service.get_option_quote = AsyncMock(return_value=OptionQuote(
            symbol="AAPL240119C00150000", underlying_symbol="AAPL", strike=Decimal(150),
            expiry=date(2024, 1, 19), type="call", price=Decimal(5), currency="USD",
            provider="test",
        ))
        service.get_option_chain = AsyncMock(return_value=OptionChain(
            underlying_symbol="I:SPX", expiry=date(2024, 1, 19), options=[], provider="test",
        ))
        factory.return_value = service
        await _tool_get_option_quote({"symbol": "AAPL", "option_id": "O:aapl240119c00150000"})
        assert service.get_option_quote.call_args.args == (
            ParsedSymbol("AAPL", "stock"), "AAPL240119C00150000",
        )
        await _tool_get_option_chain({"symbol": "^SPX", "expiry": "2024-01-19"})
        assert service.get_option_chain.call_args.args[0] == ParsedSymbol("SPX", "index")
        with pytest.raises(DataValidationError):
            await _tool_get_option_chain({"symbol": "F:ES", "expiry": "2024-01-19"})


def test_tool_schemas_document_namespaces_and_share_sec_type_enum():
    from app.api.mcp import TOOL_REGISTRY

    tools = {tool["name"]: tool["inputSchema"]["properties"] for tool in TOOL_REGISTRY}
    for name in (
        "get_last_price", "get_historical_prices", "get_implied_volatility",
        "get_implied_volatility_history", "get_implied_volatility_stats",
    ):
        assert tools[name]["sec_type"]["enum"] == ["stock", "etf", "index", "future"]
        description = tools[name]["symbol"]["description"]
        for token in ("F:ES", "I:SPX", "^SPX", "/ES", "403", "501"):
            assert token in description


@pytest.mark.asyncio
async def test_mcp_not_entitled_error_code_through_tool_call():
    from app.api.mcp import _handle_json_rpc
    from app.utils.errors import ProviderNotEntitledError

    with patch("app.api.mcp._price_service") as factory:
        service = MagicMock()
        service.get_latest_price = AsyncMock(
            side_effect=ProviderNotEntitledError("polygon", symbol="I:SPX")
        )
        factory.return_value = service
        response = await _handle_json_rpc(
            "tools/call",
            {"name": "get_last_price", "arguments": {"symbol": "I:SPX"}},
            7,
        )
    assert response["error"]["code"] == "PROVIDER_NOT_ENTITLED"
