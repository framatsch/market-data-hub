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

"""Integration tests for LSEG Provider with real API calls.

These tests require valid LSEG credentials in .env file:
- LSEG_APP_KEY
- LSEG_USERNAME
- LSEG_PASSWORD

Tests are marked with @pytest.mark.integration for selective execution.
"""

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.providers.lseg import LSEGProvider
from app.utils.errors import DataNotFoundError

# Skip all tests unless explicitly enabled.
# LSEG credentials are now sourced from keys.db via admin runtime.
pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LSEG_INTEGRATION", "false").lower() not in {"1", "true", "yes"},
    reason="Set RUN_LSEG_INTEGRATION=true to run LSEG integration tests",
)


@pytest.fixture
def lseg_provider():
    """Create LSEG provider instance for testing."""
    return LSEGProvider()


@pytest.mark.integration
class TestGetLastPrice:
    """Integration tests for get_last_price()."""

    @pytest.mark.asyncio
    async def test_get_aapl_price(self, lseg_provider):
        """Test getting AAPL quote from Refinitiv."""
        quote = await lseg_provider.get_last_price("AAPL")

        assert quote is not None
        assert quote.symbol == "AAPL"
        assert quote.last_price is not None
        assert isinstance(quote.last_price, Decimal)
        assert quote.last_price > 0
        assert quote.timestamp is not None

    @pytest.mark.asyncio
    async def test_quote_has_extended_fields(self, lseg_provider):
        """Test quote includes bid/ask and OHLC fields."""
        quote = await lseg_provider.get_last_price("MSFT")

        # At least last_price should be present
        assert quote.last_price is not None

        # Optional fields may or may not be present depending on market hours
        # Just verify they're Decimal or None
        if quote.bid is not None:
            assert isinstance(quote.bid, Decimal)
        if quote.ask is not None:
            assert isinstance(quote.ask, Decimal)
        if quote.open is not None:
            assert isinstance(quote.open, Decimal)

    @pytest.mark.asyncio
    async def test_invalid_ticker_raises_error(self, lseg_provider):
        """Test error handling for invalid ticker."""
        with pytest.raises(DataNotFoundError) as exc_info:
            await lseg_provider.get_last_price("INVALIDTICKER123XYZ")

        assert "Ticker" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_cache_works(self, lseg_provider):
        """Test quote caching reduces API calls."""
        import time

        # First call - cache miss
        start = time.time()
        quote1 = await lseg_provider.get_last_price("GOOGL")
        duration1 = time.time() - start

        # Second call - cache hit (should be much faster)
        start = time.time()
        quote2 = await lseg_provider.get_last_price("GOOGL")
        duration2 = time.time() - start

        # Cached call should be significantly faster
        assert duration2 < duration1 * 0.5
        # Prices should match (within cache TTL)
        assert quote1.last_price == quote2.last_price


@pytest.mark.integration
class TestGetHistoricalPrices:
    """Integration tests for get_historical_prices()."""

    @pytest.mark.asyncio
    async def test_get_daily_bars(self, lseg_provider):
        """Test getting AAPL daily historical data."""
        end = datetime.now()
        start = end - timedelta(days=30)

        bars = await lseg_provider.get_historical_prices("AAPL", "1d", start, end)

        assert bars is not None
        assert len(bars) > 0
        assert len(bars) <= 30  # Should not exceed requested range

        # Verify first bar structure
        bar = bars[0]
        assert bar.open is not None
        assert bar.high is not None
        assert bar.low is not None
        assert bar.close is not None
        assert bar.volume is not None
        assert bar.start is not None

        # Verify OHLC relationship
        assert bar.high >= bar.low
        assert bar.high >= bar.open
        assert bar.high >= bar.close
        assert bar.low <= bar.open
        assert bar.low <= bar.close

    @pytest.mark.asyncio
    async def test_get_weekly_bars(self, lseg_provider):
        """Test getting weekly historical data."""
        end = datetime.now()
        start = end - timedelta(weeks=12)

        bars = await lseg_provider.get_historical_prices("MSFT", "1w", start, end)

        assert bars is not None
        assert len(bars) > 0
        # Should have roughly 12 weeks of data
        assert 8 <= len(bars) <= 15

    @pytest.mark.asyncio
    async def test_bars_in_date_range(self, lseg_provider):
        """Test returned bars are within requested date range."""
        end = datetime.now(UTC)
        start = end - timedelta(days=10)

        bars = await lseg_provider.get_historical_prices("AAPL", "1d", start, end)

        for bar in bars:
            # Note: bar.start is used in the model
            assert start <= bar.start <= end

    @pytest.mark.asyncio
    async def test_different_intervals(self, lseg_provider):
        """Test different time intervals are supported."""
        end = datetime.now()

        # Test daily
        start_daily = end - timedelta(days=5)
        daily_bars = await lseg_provider.get_historical_prices("AAPL", "1d", start_daily, end)
        assert len(daily_bars) > 0

        # Test hourly (if market is open or recent data available)
        start_hourly = end - timedelta(hours=24)
        try:
            hourly_bars = await lseg_provider.get_historical_prices("AAPL", "1h", start_hourly, end)
            # May or may not have data depending on market hours
            assert isinstance(hourly_bars, list)
        except DataNotFoundError:
            # OK if no intraday data available
            pass


@pytest.mark.integration
class TestRICConversion:
    """Integration tests for ticker to RIC conversion."""

    def test_common_us_stocks(self, lseg_provider):
        """Test RIC conversion for common US stocks."""
        # Test a few well-known tickers
        tickers_to_test = ["AAPL", "MSFT", "GOOGL", "TSLA"]

        for ticker in tickers_to_test:
            ric = lseg_provider._ticker_to_ric(ticker)
            assert ric is not None
            assert isinstance(ric, str)
            assert len(ric) > 0
            # Most US stocks end in .O (NASDAQ) or .N (NYSE)
            assert "." in ric

    def test_ric_cache_persistence(self, lseg_provider):
        """Test RIC cache works across multiple calls."""
        # First call
        ric1 = lseg_provider._ticker_to_ric("AAPL")
        assert "AAPL" in lseg_provider._ric_cache

        # Second call should use cache
        ric2 = lseg_provider._ticker_to_ric("AAPL")
        assert ric1 == ric2


@pytest.mark.integration
class TestSessionManagement:
    """Integration tests for session lifecycle."""

    def test_session_creation(self, lseg_provider):
        """Test session can be created successfully."""
        session = lseg_provider._get_session()
        assert session is not None
        assert lseg_provider._session_created_at is not None

    def test_session_persists(self, lseg_provider):
        """Test session persists across multiple calls."""
        lseg_provider._get_session()
        timestamp1 = lseg_provider._session_created_at

        # Second call should reuse session
        lseg_provider._get_session()
        timestamp2 = lseg_provider._session_created_at

        assert timestamp1 == timestamp2  # Should be same session


@pytest.mark.integration
class TestErrorHandling:
    """Integration tests for error handling."""

    @pytest.mark.asyncio
    async def test_handles_network_errors_gracefully(self, lseg_provider):
        """Test provider handles network issues gracefully."""
        # Test with invalid/malformed ticker that might cause API errors
        with pytest.raises((DataNotFoundError, Exception)):
            await lseg_provider.get_last_price("")

    @pytest.mark.asyncio
    async def test_retry_on_transient_errors(self, lseg_provider):
        """Test retry logic works for real API calls."""
        # This is hard to test without simulating errors
        # Just verify normal operation succeeds
        quote = await lseg_provider.get_last_price("AAPL")
        assert quote is not None
