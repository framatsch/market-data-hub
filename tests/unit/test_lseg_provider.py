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

"""Unit tests for LSEG Provider with mocked API calls."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import threading
from unittest.mock import Mock, patch

import pytest

from app.providers.lseg import LSEGProvider
from app.utils.errors import DataNotFoundError, ProviderConnectionError


class TestRICCaching:
    """Test RIC conversion caching logic."""

    def test_ric_cache_hit(self):
        """Test RIC cache returns cached value without API call."""
        provider = LSEGProvider()
        provider._ric_cache = {
            "AAPL": ("AAPL.O", datetime.now(UTC))
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
        old_timestamp = datetime.now(UTC) - timedelta(hours=25)
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
                    assert (datetime.now(UTC) - provider._ric_cache["AAPL"][1]).total_seconds() < 10

    def test_ric_search_retries_once_after_empty_results(self):
        """Test empty RIC search results trigger one forced session refresh."""
        provider = LSEGProvider()

        import pandas as pd
        empty_response = Mock()
        empty_response.data.df = pd.DataFrame()
        success_response = Mock()
        success_response.data.df = pd.DataFrame({'RIC': ['META.O'], 'TickerSymbol': ['META']})

        get_session_calls = []

        def mock_get_session():
            get_session_calls.append(True)

        with patch('refinitiv.data.content.search.Definition') as mock_search:
            mock_search.return_value.get_data.side_effect = [empty_response, empty_response, success_response]

            with patch.object(provider, '_get_session', side_effect=mock_get_session):
                with patch.object(provider, '_throttle'):
                    ric = provider._ticker_to_ric("META")

        assert ric == "META.O"
        assert len(get_session_calls) == 2

    def test_ric_search_retries_once_after_closed_session_error(self):
        """Test closed-session search errors trigger one forced session refresh."""
        provider = LSEGProvider()

        import pandas as pd
        success_response = Mock()
        success_response.data.df = pd.DataFrame({'RIC': ['META.O'], 'TickerSymbol': ['META']})

        get_session_calls = []

        def mock_get_session():
            get_session_calls.append(True)

        with patch('refinitiv.data.content.search.Definition') as mock_search:
            mock_search.return_value.get_data.side_effect = [
                Exception("Session is not opened. Can't send any request"),
                success_response,
            ]

            with patch.object(provider, '_get_session', side_effect=mock_get_session):
                with patch.object(provider, '_throttle'):
                    ric = provider._ticker_to_ric("META")

        assert ric == "META.O"
        assert len(get_session_calls) == 2


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
        provider._session_created_at = datetime.now(UTC) - timedelta(hours=1)

        # Track if _create_session is called
        create_called = []

        def mock_create():
            create_called.append(True)
            provider._session = Mock()
            provider._session_created_at = datetime.now(UTC)

        # Mock rd.session.default
        with patch('app.providers.lseg.rd.session') as mock_session:
            mock_session.get_default.return_value = provider._session
            provider._create_session = mock_create
            provider._get_session()

            assert len(create_called) == 1  # Should have called _create_session

    def test_session_not_refreshed_if_valid(self):
        """Test valid session is not refreshed."""
        provider = LSEGProvider()
        provider._session = SimpleNamespace(opened=True)
        provider._session_created_at = datetime.now(UTC) - timedelta(minutes=30)

        # Mock to check _create_session not called
        create_called = []

        def mock_create():
            create_called.append(True)

        # Mock rd.session.default
        with patch('app.providers.lseg.rd.session') as mock_session:
            mock_session.get_default.return_value = provider._session
            provider._create_session = mock_create
            provider._get_session()

            assert len(create_called) == 0  # Should NOT have called _create_session

    def test_session_refreshes_if_existing_session_is_closed(self):
        """Test closed session refreshes even before TTL expires."""
        provider = LSEGProvider()
        provider._session = SimpleNamespace(opened=False)
        provider._session_created_at = datetime.now(UTC) - timedelta(minutes=5)

        create_called = []

        def mock_create():
            create_called.append(True)
            provider._session = SimpleNamespace(opened=True)
            provider._session_created_at = datetime.now(UTC)

        provider._create_session = mock_create

        with patch('app.providers.lseg.rd.session') as mock_session:
            mock_session.get_default.return_value = provider._session
            session = provider._get_session()

        assert len(create_called) == 1
        assert session.opened is True

    def test_session_unknown_state_is_treated_as_open_for_compatibility(self):
        """Test session objects without state attributes keep existing behavior."""
        provider = LSEGProvider()
        session = object()

        assert provider._is_session_open(session) is True

    def test_session_reinstates_open_session_if_default_session_is_missing(self):
        """Test missing Refinitiv default session is restored from provider session."""
        provider = LSEGProvider()
        provider._session = SimpleNamespace(opened=True)
        provider._session_created_at = datetime.now(UTC) - timedelta(minutes=5)

        create_called = []

        def mock_create():
            create_called.append(True)
            provider._session = SimpleNamespace(opened=True)
            provider._session_created_at = datetime.now(UTC)

        provider._create_session = mock_create

        with patch('app.providers.lseg.rd.session') as mock_session:
            mock_session.get_default.side_effect = [Exception("No default session"), provider._session]
            provider._get_session()

        assert len(create_called) == 0
        mock_session.set_default.assert_called_once_with(provider._session)

    def test_session_replaces_closed_default_with_open_provider_session(self):
        """Test closed Refinitiv default session is replaced by provider session."""
        provider = LSEGProvider()
        provider._session = SimpleNamespace(opened=True)
        provider._session_created_at = datetime.now(UTC) - timedelta(minutes=5)
        closed_default_session = SimpleNamespace(opened=False)

        create_called = []

        def mock_create():
            create_called.append(True)
            provider._session = SimpleNamespace(opened=True)
            provider._session_created_at = datetime.now(UTC)

        provider._create_session = mock_create

        with patch('app.providers.lseg.rd.session') as mock_session:
            mock_session.get_default.side_effect = [closed_default_session, provider._session]
            provider._get_session()

        assert len(create_called) == 0
        mock_session.set_default.assert_called_once_with(provider._session)

    def test_ric_search_session_closed_error_is_not_reported_as_not_found(self):
        """Test closed-session search errors remain connection failures."""
        provider = LSEGProvider()

        with patch.object(provider, '_get_session'):
            with patch.object(provider, '_throttle'):
                with patch('refinitiv.data.content.search.Definition') as mock_search:
                    mock_search.return_value.get_data.side_effect = Exception(
                        "Session is not opened. Can't send any request"
                    )

                    with pytest.raises(ProviderConnectionError) as exc_info:
                        provider._ticker_to_ric("AAPL")

        assert "session is not open" in str(exc_info.value).lower()
        assert provider._session is None
        assert provider._session_created_at is None

    def test_ric_search_non_session_errors_still_report_not_found(self):
        """Test ordinary search failures still fall through to ticker not found."""
        provider = LSEGProvider()

        with patch.object(provider, '_get_session'):
            with patch.object(provider, '_throttle'):
                with patch('refinitiv.data.content.search.Definition') as mock_search:
                    mock_search.return_value.get_data.side_effect = Exception("temporary search parser error")

                    with pytest.raises(DataNotFoundError):
                        provider._ticker_to_ric("AAPL")

    def test_session_open_auth_output_surfaces_auth_error(self):
        """Test SDK auth output is returned as an authentication failure."""
        provider = LSEGProvider()

        class FakeSession:
            opened = False

            def open(self):
                print("[Error 400] - {'error': 'access_denied', 'error_description': 'Invalid username or password.'}")

        output = provider._open_session(FakeSession())
        with pytest.raises(ProviderConnectionError) as exc_info:
            provider._raise_if_auth_error(output)

        assert "Invalid username or password" in str(exc_info.value)
        assert "access_denied" in exc_info.value.details["error"]

    def test_session_open_auth_output_surfaces_auth_error_when_open_raises(self):
        """Test SDK auth output is preserved when open raises too."""
        provider = LSEGProvider()

        class FakeSession:
            opened = False

            def open(self):
                print("[Error 400] - {'error': 'access_denied', 'error_description': 'Invalid username or password.'}")
                raise RuntimeError("session open failed")

        with pytest.raises(ProviderConnectionError) as exc_info:
            provider._open_session(FakeSession())

        assert "Invalid username or password" in str(exc_info.value)
        assert "access_denied" in exc_info.value.details["error"]


class TestQuoteCaching:
    """Test quote caching functionality."""

    def test_cache_returns_valid_quote(self):
        """Test cached quote is returned if valid."""
        provider = LSEGProvider()

        cached_quote = Mock()
        cached_quote.symbol = "AAPL"
        provider._quote_cache = {
            "AAPL": (cached_quote, datetime.now(UTC))
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
        old_timestamp = datetime.now(UTC) - timedelta(seconds=10)
        provider._quote_cache = {
            "AAPL": (old_quote, old_timestamp)
        }

        # Assuming cache TTL is 5 seconds (default)
        result = provider._get_cached_quote("AAPL")
        assert result is None


@pytest.mark.asyncio
async def test_test_connection_success(monkeypatch):
    provider = LSEGProvider()
    monkeypatch.setattr(provider, "_get_session", lambda: SimpleNamespace(opened=True))

    result = await provider.test_connection()

    assert result["status_code"] == 200
    assert result["success"] is True
    assert result["message"] == "LSEG session active"


@pytest.mark.asyncio
async def test_test_connection_auth_failure(monkeypatch):
    provider = LSEGProvider()
    monkeypatch.setattr(provider, "_create_session", lambda: (_ for _ in ()).throw(Exception("authentication failed")))

    result = await provider.test_connection()

    assert result["status_code"] == 401
    assert result["success"] is False
    assert result["message"] == "LSEG authentication failed"


@pytest.mark.asyncio
async def test_test_connection_service_unavailable(monkeypatch):
    provider = LSEGProvider()
    monkeypatch.setattr(provider, "_create_session", lambda: (_ for _ in ()).throw(Exception("service unavailable")))

    result = await provider.test_connection()

    assert result["status_code"] == 503
    assert result["success"] is False
    assert result["message"] == "LSEG service unavailable"


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


@pytest.mark.asyncio
async def test_get_last_price_runs_sync_work_off_event_loop_thread(monkeypatch):
    provider = LSEGProvider()
    event_loop_thread_id = threading.get_ident()
    observed: dict[str, int] = {}

    def fake_sync(symbol: str, market_data_type=None):
        observed["thread_id"] = threading.get_ident()
        class Quote:
            pass
        quote = Quote()
        quote.provider = "lseg"
        return quote

    monkeypatch.setattr(provider, "_get_last_price_sync", fake_sync)

    result = await provider.get_last_price("AAPL")

    assert result.provider == "lseg"
    assert observed["thread_id"] != event_loop_thread_id
