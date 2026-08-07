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

"""Integration tests for Polygon.io Provider."""

import os
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.providers.polygon import PolygonProvider

# Skip unless explicitly enabled.
pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POLYGON_INTEGRATION", "false").lower() not in {"1", "true", "yes"},
    reason="Set RUN_POLYGON_INTEGRATION=true to run Polygon integration tests",
)

@pytest.fixture
async def polygon_provider():
    """Create Polygon provider instance."""
    provider = PolygonProvider()
    yield provider
    await provider.close()

@pytest.mark.integration
class TestPolygonPrices:
    """Integration tests for Polygon price data."""

    @pytest.mark.asyncio
    async def test_get_aapl_price(self, polygon_provider):
        """Test getting AAPL quote from Polygon."""
        quote = await polygon_provider.get_last_price("AAPL")

        assert quote is not None
        assert quote.symbol == "AAPL"
        assert quote.last_price > 0
        assert isinstance(quote.last_price, Decimal)
        assert quote.provider == "polygon"

    @pytest.mark.asyncio
    async def test_get_historical_daily(self, polygon_provider):
        """Test getting daily bars from Polygon."""
        end = datetime.now()
        start = end - timedelta(days=5)
        
        bars = await polygon_provider.get_historical_prices("MSFT", "1d", start, end)
        
        assert bars is not None
        assert len(bars) > 0
        assert bars[0].symbol == "MSFT"
        assert bars[0].close > 0

@pytest.mark.integration
class TestPolygonOptions:
    """Integration tests for Polygon options data."""

    @pytest.mark.asyncio
    async def test_get_option_chain_aapl(self, polygon_provider):
        """Test getting AAPL option chain."""
        # Need a future expiry date. Let's find one roughly 30 days out.
        # For a real test, you'd want a specific known expiry.
        from datetime import date, timedelta
        expiry = date.today() + timedelta(days=30)
        
        # Polygon API might return empty if the date isn't a Friday or doesn't have contracts
        # but the method should at least return a valid object
        chain = await polygon_provider.get_option_chain("AAPL", expiry)
        
        assert chain is not None
        assert chain.underlying_symbol == "AAPL"
        assert isinstance(chain.options, list)

@pytest.mark.integration
class TestPolygonReference:
    """Integration tests for Polygon reference data (Ticker Details, Market Status)."""

    @pytest.mark.asyncio
    async def test_get_market_status(self, polygon_provider):
        """Test getting market status from Polygon."""
        status = await polygon_provider.get_market_status()
        
        assert status is not None
        assert status.provider == "polygon"
        assert status.market in ["open", "closed", "extended-hours"]

    @pytest.mark.asyncio
    async def test_get_company_profile(self, polygon_provider):
        """Test getting company profile from Polygon."""
        profile = await polygon_provider.get_company_profile("AAPL")
        
        assert profile is not None
        assert profile.symbol == "AAPL"
        assert "Apple" in profile.name
        assert profile.provider == "polygon"
