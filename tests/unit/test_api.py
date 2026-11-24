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

import csv
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.dependencies import (
    get_company_service,
    get_news_service,
    get_options_service,
    get_price_service,
)
from app.main import app
from app.models.company import CompanyProfile, CompanySummary
from app.models.news import NewsArticle
from app.models.options import OptionChain, OptionQuote
from app.models.price import PriceBar, PriceQuote


@pytest.fixture
def mock_price_service():
    return MagicMock()

@pytest.fixture
def mock_company_service():
    return MagicMock()

@pytest.fixture
def mock_options_service():
    return MagicMock()

@pytest.fixture
def mock_news_service():
    return MagicMock()
@pytest.fixture
def client(mock_price_service, mock_company_service, mock_options_service, mock_news_service):
    app.dependency_overrides[get_price_service] = lambda: mock_price_service
    app.dependency_overrides[get_company_service] = lambda: mock_company_service
    app.dependency_overrides[get_options_service] = lambda: mock_options_service
    app.dependency_overrides[get_news_service] = lambda: mock_news_service
    yield TestClient(app)
    app.dependency_overrides.clear()

def test_get_last_price(client, mock_price_service):
    mock_price_service.get_latest_price = AsyncMock(return_value=PriceQuote(
        symbol="AAPL", price=Decimal("150.00"), currency="USD", 
        timestamp=datetime.now(), provider="test"
    ))
    
    response = client.get("/prices/AAPL/last")
    assert response.status_code == 200
    assert response.json()["data"]["symbol"] == "AAPL"

def test_get_historical_prices(client, mock_price_service):
    mock_price_service.get_historical_prices = AsyncMock(return_value=[
        PriceBar(symbol="AAPL", start=datetime.now(), end=datetime.now(), 
                 open=Decimal("149.00"), high=Decimal("151.00"), 
                 low=Decimal("148.00"), close=Decimal("150.00"), 
                 volume=1000, provider="test")
    ])
    
    response = client.get("/prices/AAPL/history?interval=1d&extended_hours=true")
    assert response.status_code == 200
    assert len(response.json()["data"]) == 1
    
    # Verify parameter passing
    mock_price_service.get_historical_prices.assert_called_once()
    kwargs = mock_price_service.get_historical_prices.call_args[0]
    assert kwargs[4] == True  # extended_hours is the 5th argument

def test_get_company_profile(client, mock_company_service):
    mock_company_service.get_company_profile = AsyncMock(return_value=CompanyProfile(
        symbol="AAPL", name="Apple Inc.", exchange="NASDAQ", currency="USD", provider="test"
    ))
    
    response = client.get("/companies/AAPL")
    assert response.status_code == 200
    assert response.json()["data"]["name"] == "Apple Inc."

def test_search_companies(client, mock_company_service):
    mock_company_service.search_companies = AsyncMock(return_value=[
        CompanySummary(symbol="AAPL", name="Apple Inc.", exchange="NASDAQ", provider="test")
    ])
    
    response = client.get("/companies/search?q=Apple")
    assert response.status_code == 200
    assert len(response.json()["data"]) == 1

def test_get_option_chain(client, mock_options_service):
    mock_options_service.get_option_chain = AsyncMock(return_value=OptionChain(
        underlying_symbol="AAPL", expiry=date(2024, 1, 19), options=[], provider="test"
    ))
    
    response = client.get("/options/AAPL/chain?expiry=2024-01-19")
    assert response.status_code == 200
    assert response.json()["data"]["underlying_symbol"] == "AAPL"
    assert response.json()["data"]["underlying_contract"] is None


def test_futures_option_chain_metadata_and_csv(client, mock_options_service):
    expiry = date(2026, 12, 18)
    options = [
        OptionQuote(
            symbol=f"ESZ6 {side[0].upper()}7250", underlying_symbol="F:ES",
            strike=Decimal(7250), expiry=expiry, type=side, price=Decimal(50), provider="ibkrweb",
        )
        for side in ("call", "put")
    ]
    metadata = dict(
        underlying_contract="ESZ6", underlying_price="7245.50", multiplier="50",
        trading_class="ES", exchange="CME",
    )
    mock_options_service.get_option_chain = AsyncMock(return_value=OptionChain(
        underlying_symbol="F:ES", expiry=expiry, options=options, provider="ibkrweb", **metadata,
    ))
    path = "/options/F:ES/chain?expiry=2026-12-18&trading_class=es"
    response = client.get(path)
    assert response.status_code == 200
    assert {key: response.json()["data"][key] for key in metadata} == metadata
    assert mock_options_service.get_option_chain.call_args.kwargs["trading_class"] == "es"
    response = client.get(f"{path}&format=csv")
    assert response.status_code == 200
    rows = list(csv.DictReader(response.text.splitlines()))
    assert [row["symbol"] for row in rows] == [quote.symbol for quote in options]
    assert all({key: row[key] for key in metadata} == metadata for row in rows)

def test_get_option_quote(client, mock_options_service):
    mock_options_service.get_option_quote = AsyncMock(return_value=OptionQuote(
        symbol="AAPL240119C00150000", underlying_symbol="AAPL", strike=Decimal(150), 
        expiry=date(2024, 1, 19), type="call", price=Decimal("5.00"), 
        currency="USD", provider="test"
    ))
    
    response = client.get("/options/AAPL/quote/AAPL240119C00150000")
    assert response.status_code == 200
    assert response.json()["data"]["symbol"] == "AAPL240119C00150000"

def test_get_company_news(client, mock_news_service):
    mock_news_service.registry.default_news_provider = "mock"
    mock_news_service.get_company_news = AsyncMock(return_value=[
        NewsArticle(article_id="1", title="Test News", url="http://test.com", 
                    published_at=datetime.now(), source="test", summary="...")
    ])
    
    response = client.get("/companies/AAPL/news?days=7")
    assert response.status_code == 200
    assert len(response.json()["data"]) == 1
