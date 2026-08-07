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
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.common import MarketStatus
from app.models.company import CompanyProfile, CompanySummary
from app.models.news import NewsArticle
from app.models.options import OptionChain, OptionQuote
from app.models.price import PriceBar, PriceQuote
from app.services.company_service import CompanyService
from app.services.news_service import NewsService
from app.services.options_service import OptionsService
from app.services.price_service import PriceService


@pytest.fixture
def mock_registry():
    return MagicMock()

@pytest.fixture
def price_service(mock_registry):
    return PriceService(registry=mock_registry)

@pytest.fixture
def company_service(mock_registry):
    return CompanyService(registry=mock_registry)

@pytest.fixture
def options_service(mock_registry):
    return OptionsService(registry=mock_registry)

@pytest.fixture
def news_service(mock_registry):
    return NewsService(registry=mock_registry)

# ... (previous service tests) ...

@pytest.mark.asyncio
async def test_get_option_chain(options_service, mock_registry):
    mock_provider = MagicMock()
    mock_provider.get_option_chain = AsyncMock(return_value=OptionChain(
        underlying_symbol="AAPL", expiry=date(2024, 1, 19), options=[], provider="test"
    ))
    mock_registry.get_options_provider.return_value = mock_provider
    
    result = await options_service.get_option_chain("AAPL", date(2024, 1, 19), provider_name="test")
    
    assert result.underlying_symbol == "AAPL"
    mock_registry.get_options_provider.assert_called_with("test")
    mock_provider.get_option_chain.assert_called_once()

@pytest.mark.asyncio
async def test_get_option_quote(options_service, mock_registry):
    mock_provider = MagicMock()
    mock_provider.get_option_quote = AsyncMock(return_value=OptionQuote(
        symbol="AAPL240119C00150000", underlying_symbol="AAPL", strike=Decimal(150), 
        expiry=date(2024, 1, 19), type="call", price=Decimal("5.00"), 
        currency="USD", provider="test"
    ))
    mock_registry.get_options_provider.return_value = mock_provider
    
    result = await options_service.get_option_quote("AAPL", "AAPL240119C00150000", provider_name="test")
    
    assert result.symbol == "AAPL240119C00150000"
    mock_registry.get_options_provider.assert_called_with("test")
    mock_provider.get_option_quote.assert_called_once()

@pytest.mark.asyncio
async def test_get_company_profile(company_service, mock_registry):
    mock_provider = MagicMock()
    mock_provider.get_company_profile = AsyncMock(return_value=CompanyProfile(
        symbol="AAPL", name="Apple Inc.", exchange="NASDAQ", currency="USD", provider="test"
    ))
    mock_registry.get_company_provider.return_value = mock_provider
    
    result = await company_service.get_company_profile("AAPL", provider_name="test")
    
    assert result.symbol == "AAPL"
    mock_registry.get_company_provider.assert_called_with("test")
    mock_provider.get_company_profile.assert_called_once()

@pytest.mark.asyncio
async def test_search_companies(company_service, mock_registry):
    mock_provider = MagicMock()
    mock_provider.search_companies = AsyncMock(return_value=[
        CompanySummary(symbol="AAPL", name="Apple Inc.", exchange="NASDAQ", provider="test")
    ])
    mock_registry.get_company_provider.return_value = mock_provider
    
    result = await company_service.search_companies("Apple", provider_name="test")
    
    assert len(result) == 1
    mock_registry.get_company_provider.assert_called_with("test")
    mock_provider.search_companies.assert_called_once()

@pytest.mark.asyncio
async def test_get_latest_price(price_service, mock_registry):
    mock_provider = MagicMock()
    mock_provider.get_last_price = AsyncMock(return_value=PriceQuote(
        symbol="AAPL", price=Decimal("150.00"), currency="USD", 
        timestamp=datetime.now(), provider="test"
    ))
    mock_registry.get_price_provider.return_value = mock_provider
    
    result = await price_service.get_latest_price("AAPL", provider_name="test")
    
    assert result.symbol == "AAPL"
    mock_registry.get_price_provider.assert_called_with("test")
    mock_provider.get_last_price.assert_called_once()

@pytest.mark.asyncio
async def test_get_historical_prices(price_service, mock_registry):
    mock_provider = MagicMock()
    mock_provider.get_historical_prices = AsyncMock(return_value=[
        PriceBar(symbol="AAPL", start=datetime.now(), end=datetime.now(), 
                 open=Decimal("149.00"), high=Decimal("151.00"), 
                 low=Decimal("148.00"), close=Decimal("150.00"), 
                 volume=1000, provider="test")
    ])
    mock_registry.get_price_provider.return_value = mock_provider
    
    start = datetime(2024, 1, 1)
    end = datetime(2024, 1, 2)
    result = await price_service.get_historical_prices("AAPL", "1d", start, end, provider_name="test")
    
    assert len(result) == 1
    mock_registry.get_price_provider.assert_called_with("test")
    mock_provider.get_historical_prices.assert_called_once()

@pytest.mark.asyncio
async def test_get_market_status(price_service, mock_registry):
    mock_provider = MagicMock()
    mock_provider.get_market_status = AsyncMock(return_value=MarketStatus(
        market="open", server_time=datetime.now(), provider="test"
    ))
    mock_registry.get_price_provider.return_value = mock_provider
    
    result = await price_service.get_market_status(provider_name="test")
    
    assert result.market == "open"
    mock_registry.get_price_provider.assert_called_with("test")
    mock_provider.get_market_status.assert_called_once()

@pytest.mark.asyncio
async def test_get_company_news(news_service, mock_registry):
    mock_provider = MagicMock()
    mock_provider.get_company_news = AsyncMock(return_value=[
        NewsArticle(
            article_id="test:1",
            title="Apple News",
            summary="Summary",
            published_at=datetime.now(),
            source="Test",
            url="https://example.com/news/1",
            full_text=None,
            category=None,
            image=None,
            sentiment=None,
        )
    ])
    mock_registry.get_news_provider.return_value = mock_provider

    from_date = date(2024, 1, 1)
    to_date = date(2024, 1, 2)
    result = await news_service.get_company_news(
        "AAPL",
        from_date,
        to_date,
        provider_name="test",
        limit=10,
        offset=5,
        language="de",
        category="earnings",
    )

    assert len(result) == 1
    mock_registry.get_news_provider.assert_called_with("test")
    mock_provider.get_company_news.assert_awaited_once_with(
        symbol="AAPL",
        from_date=from_date,
        to_date=to_date,
        limit=10,
        offset=5,
        language="de",
        category="earnings",
    )

@pytest.mark.asyncio
async def test_get_company_news_uses_default_provider(news_service, mock_registry):
    mock_provider = MagicMock()
    mock_provider.get_company_news = AsyncMock(return_value=[])
    mock_registry.get_news_provider.return_value = mock_provider

    await news_service.get_company_news("AAPL", date(2024, 1, 1), date(2024, 1, 2))

    mock_registry.get_news_provider.assert_called_with(None)
