"""Unit tests for LSEG Provider with mocked API calls."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from app.providers.lseg import LSEGProvider
from app.utils.errors import ProviderConnectionError


class TestRICCaching:
    """Test RIC conversion caching logic."""

    def test_ric_cache_hit(self):
        """Test RIC cache returns cached value without API call."""
        provider = LSEGProvider()
        provider._ric_cache = {
            "AAPL": ("AAPL.O", datetime.now(timezone.utc))
        }

        # Should not make API call
        with patch('refinitiv.data.content.search.Definition') as mock_search:
            ric = provider._ticker_to_ric("AAPL")
            assert ric == "AAPL.O"
            mock_search.assert_not_called()

    def test_ric_cache_miss_searches_api(self):
        """Test RIC search when cache miss."""
        provider = LSEGProvider()

        # Mock successful search response with proper pandas-like structure
        import pandas as pd
        mock_df = pd.DataFrame({'RIC': ['AAPL.O'], 'TickerSymbol': ['AAPL']})

        mock_response = Mock()
        mock_response.data.df = mock_df

        with patch('refinitiv.data.content.search.Definition') as mock_search:
            mock_search.return_value.get_data.return_value = mock_response

            with patch.object(provider, '_get_session'):
                with patch.object(provider, '_throttle'):
                    ric = provider._ticker_to_ric("AAPL")
                    assert ric == "AAPL.O"
                    assert "AAPL" in provider._ric_cache
                    mock_search.assert_called_once()

    def test_ric_cache_expiry(self):
        """Test expired cache entries trigger new search."""
        provider = LSEGProvider()
        old_timestamp = datetime.now(timezone.utc) - timedelta(hours=25)
        provider._ric_cache = {
            "AAPL": ("AAPL.O", old_timestamp)
        }

        # Mock search with pandas DataFrame
        import pandas as pd
        mock_df = pd.DataFrame({'RIC': ['AAPL.O'], 'TickerSymbol': ['AAPL']})

        mock_response = Mock()
        mock_response.data.df = mock_df

        with patch('refinitiv.data.content.search.Definition') as mock_search:
            mock_search.return_value.get_data.return_value = mock_response

            with patch.object(provider, '_get_session'):
                with patch.object(provider, '_throttle'):
                    ric = provider._ticker_to_ric("AAPL")
                    assert ric == "AAPL.O"
                    # Should have updated cache
                    assert (datetime.now(timezone.utc) - provider._ric_cache["AAPL"][1]).total_seconds() < 10


class TestRetryLogic:
    """Test retry logic with exponential backoff."""

    def test_retry_success_on_second_attempt(self):
        """Test retry succeeds after transient error."""
        provider = LSEGProvider()

        call_count = 0
        def flaky_function():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("429 Rate Limit")
            return "success"

        with patch('time.sleep'):  # Skip actual sleep in tests
            result = provider._retry_with_backoff(flaky_function)
            assert result == "success"
            assert call_count == 2

    def test_retry_fails_after_max_attempts(self):
        """Test retry raises error after max attempts."""
        provider = LSEGProvider()

        def always_fails():
            raise Exception("500 Internal Server Error")

        with patch('time.sleep'):
            with pytest.raises(ProviderConnectionError) as exc_info:
                provider._retry_with_backoff(always_fails)

            assert "failed after 3 retries" in str(exc_info.value)

    def test_non_retryable_error_fails_immediately(self):
        """Test non-retryable errors don't trigger retry."""
        provider = LSEGProvider()

        call_count = 0
        def non_retryable():
            nonlocal call_count
            call_count += 1
            raise Exception("404 Not Found")

        with pytest.raises(Exception) as exc_info:
            provider._retry_with_backoff(non_retryable)

        assert call_count == 1  # Should not retry
        assert "404" in str(exc_info.value)


class TestSessionManagement:
    """Test session lifecycle management."""

    def test_session_refresh_after_ttl(self):
        """Test session refreshes after TTL expires."""
        provider = LSEGProvider()
        provider._session = Mock()  # Pretend we have a session
        provider._session_created_at = datetime.now(timezone.utc) - timedelta(hours=1)

        # Track if _create_session is called
        create_called = []

        def mock_create():
            create_called.append(True)
            provider._session = Mock()
            provider._session_created_at = datetime.now(timezone.utc)

        # Mock rd.session.default
        with patch('refinitiv.data.session') as mock_session:
            mock_session.default = Mock()
            provider._create_session = mock_create
            provider._get_session()

            assert len(create_called) == 1  # Should have called _create_session

    def test_session_not_refreshed_if_valid(self):
        """Test valid session is not refreshed."""
        provider = LSEGProvider()
        provider._session = Mock()
        provider._session_created_at = datetime.now(timezone.utc) - timedelta(minutes=30)

        # Mock to check _create_session not called
        create_called = []

        def mock_create():
            create_called.append(True)

        # Mock rd.session.default
        with patch('refinitiv.data.session') as mock_session:
            mock_session.default = Mock()
            provider._create_session = mock_create
            provider._get_session()

            assert len(create_called) == 0  # Should NOT have called _create_session


class TestQuoteCaching:
    """Test quote caching functionality."""

    def test_cache_returns_valid_quote(self):
        """Test cached quote is returned if valid."""
        provider = LSEGProvider()

        cached_quote = Mock()
        cached_quote.symbol = "AAPL"
        provider._quote_cache = {
            "AAPL": (cached_quote, datetime.now(timezone.utc))
        }

        result = provider._get_cached_quote("AAPL")
        assert result == cached_quote

    def test_cache_miss_returns_none(self):
        """Test cache miss returns None."""
        provider = LSEGProvider()

        result = provider._get_cached_quote("UNKNOWN")
        assert result is None

    def test_expired_cache_returns_none(self):
        """Test expired cache entry returns None."""
        provider = LSEGProvider()

        old_quote = Mock()
        old_timestamp = datetime.now(timezone.utc) - timedelta(seconds=10)
        provider._quote_cache = {
            "AAPL": (old_quote, old_timestamp)
        }

        # Assuming cache TTL is 5 seconds (default)
        result = provider._get_cached_quote("AAPL")
        assert result is None


class TestRateLimiting:
    """Test rate limiting and throttling."""

    def test_throttle_respects_rate_limit(self):
        """Test throttle enforces rate limit."""
        provider = LSEGProvider()

        # Fill up request queue to limit
        import time
        now = time.time()
        for _ in range(10):  # Default rate limit
            provider._request_times.append(now)

        # Next request should trigger sleep
        with patch('time.sleep') as mock_sleep:
            with patch('time.time', return_value=now + 0.5):  # Simulate 0.5s passed
                provider._throttle()
                # Should sleep for remaining time to complete 1 second
                mock_sleep.assert_called_once()
                sleep_duration = mock_sleep.call_args[0][0]
                assert 0 < sleep_duration <= 0.5
