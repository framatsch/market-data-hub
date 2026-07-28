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

import asyncio
import io
import logging
import time
from collections import deque
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, TypeVar, cast

import pandas as pd

from app.config import settings
from app.models.company import CompanyProfile, CompanySummary
from app.models.news import NewsArticle
from app.models.price import PriceBar, PriceQuote
from app.providers.base import BaseCompanyProvider, BaseNewsProvider, BasePriceProvider
from app.providers.credentials import get_provider_credential_sync
from app.utils.errors import (
    DataNotFoundError,
    DataValidationError,
    ProviderConnectionError,
    ProviderError,
)

logger = logging.getLogger(__name__)
_REFINITIV_HTTPX_PROXY_PATCHED = False

# Lazy import refinitiv to avoid import errors if not installed
try:
    import refinitiv.data as rd
    from refinitiv.data.content import historical_pricing, search
    REFINITIV_AVAILABLE = True
except ImportError:
    REFINITIV_AVAILABLE = False
    logger.warning("refinitiv.data not available - LSEG provider will not work")

T = TypeVar('T')


def _patch_refinitiv_httpx_proxy_handling() -> None:
    """Patch refinitiv-data proxy handling for httpx>=0.26.

    refinitiv-data 1.6.2 passes a proxies dict into httpx.Client(proxy=...),
    but httpx>=0.26 expects a single proxy URL for `proxy`.
    """
    global _REFINITIV_HTTPX_PROXY_PATCHED
    if _REFINITIV_HTTPX_PROXY_PATCHED or not REFINITIV_AVAILABLE:
        return

    try:
        from refinitiv.data._core.session import http_service
    except Exception:
        return

    original_sync = http_service.get_httpx_client
    original_async = http_service.get_httpx_client_async

    def _normalize_proxy(proxies: Any) -> Any:
        if not isinstance(proxies, dict):
            return proxies

        for key in ("https://", "http://", "all://", "https", "http", "all"):
            url = proxies.get(key)
            if url:
                return url

        return None

    def patched_get_httpx_client(proxies: Any, **kwargs: Any) -> Any:
        return original_sync(_normalize_proxy(proxies), **kwargs)

    def patched_get_httpx_client_async(proxies: Any, **kwargs: Any) -> Any:
        return original_async(_normalize_proxy(proxies), **kwargs)

    http_service.get_httpx_client = patched_get_httpx_client
    http_service.get_httpx_client_async = patched_get_httpx_client_async
    _REFINITIV_HTTPX_PROXY_PATCHED = True
    logger.info("Applied refinitiv-data proxy compatibility patch for httpx>=0.26")


class LSEGProvider(BaseCompanyProvider, BasePriceProvider, BaseNewsProvider):
    """Refinitiv (LSEG) provider for stock prices, company data, and news.

    ⚠️  Options NOT supported - use IBKR provider instead.
    LSEG subscription lacks 'trapi.data.pricing.read' scope required for real-time Greeks.
    """

    def __init__(self) -> None:
        if not REFINITIV_AVAILABLE:
            raise ImportError("refinitiv.data package is required for LSEG provider")

        _patch_refinitiv_httpx_proxy_handling()

        # Session management
        self._session = None
        self._session_created_at: datetime | None = None
        self._session_ttl = timedelta(minutes=55)  # Refresh before 1h expiry

        # RIC conversion cache (ticker -> RIC mapping)
        self._ric_cache: dict[str, tuple[str, datetime]] = {}
        self._ric_cache_ttl = timedelta(hours=24)

        # Quote caching for performance
        self._quote_cache: dict[str, tuple[PriceQuote, datetime]] = {}

        # Rate limiting — no maxlen: manual popleft manages window to avoid eviction races
        self._request_times: deque[float] = deque()

        logger.info("LSEGProvider initialized")

    # ========================================================================
    # Session Management
    # ========================================================================

    async def test_connection(self) -> dict[str, Any]:
        """Validate LSEG credentials by opening a Refinitiv session."""
        return await asyncio.to_thread(self._test_connection_sync)

    def _test_connection_sync(self) -> dict[str, Any]:
        try:
            self._get_session()

            return {
                "status_code": 200,
                "success": True,
                "message": "LSEG session active",
                "details": {"session_created_at": self._session_created_at.isoformat() if self._session_created_at else None},
            }
        except Exception as exc:
            error_message = str(exc)
            lowered = error_message.lower()
            if any(token in lowered for token in ("auth", "unauthor", "forbidden", "invalid credential", "signon")):
                return {
                    "status_code": 401,
                    "success": False,
                    "message": "LSEG authentication failed",
                    "details": {"error": error_message},
                }
            return {
                "status_code": 503,
                "success": False,
                "message": "LSEG service unavailable",
                "details": {"error": error_message},
            }

    def _get_session(self) -> Any:
        """Get or create Refinitiv session with smart refresh."""
        now = datetime.now(UTC)

        # Check if session needs refresh
        if self._session is None or self._session_created_at is None:
            logger.debug("Session is None or not created yet, creating new session...")
            needs_refresh = True
        elif not self._is_session_open(self._session):
            logger.info("Refinitiv session is not open, refreshing...")
            needs_refresh = True
        elif not self._is_default_session_open():
            logger.info("Refinitiv default session is not open, refreshing...")
            needs_refresh = True
        elif now - self._session_created_at > self._session_ttl:
            needs_refresh = True
            logger.info(f"Session TTL exceeded ({self._session_ttl}), refreshing...")
        else:
            age = (now - self._session_created_at).total_seconds()
            logger.debug(f"Session valid, age: {age:.1f}s")
            needs_refresh = False

        if needs_refresh:
            self._create_session()

        if self._session is None or not self._is_session_open(self._session) or not self._is_default_session_open():
            raise ProviderConnectionError("LSEG session is not open after initialization")

        return self._session

    def _is_default_session_open(self) -> bool:
        """Return whether Refinitiv's global default session is our open session."""
        try:
            default_session = rd.session.get_default()
        except Exception:
            if self._session is not None and self._is_session_open(self._session):
                rd.session.set_default(self._session)
                return True
            return False

        if default_session is not self._session:
            if self._session is not None and self._is_session_open(self._session):
                rd.session.set_default(self._session)
                return True
            return self._is_session_open(default_session)

        return self._is_session_open(default_session)

    def _is_session_open(self, session: Any) -> bool:
        """Return whether a Refinitiv session object is currently open."""
        for attr_name in ("is_open", "opened", "is_opened"):
            attr = getattr(session, attr_name, None)
            if callable(attr):
                return bool(attr())
            if attr is not None:
                return bool(attr)

        state = getattr(session, "state", None)
        if state is not None:
            state_value = getattr(state, "name", state)
            normalized_state = str(state_value).lower()
            if any(token in normalized_state for token in ("closed", "close", "pending")):
                return False
            return any(token in normalized_state for token in ("opened", "open"))

        return True

    def _create_session(self) -> None:
        """Create new Refinitiv session."""
        try:
            logger.info("Creating new Refinitiv session...")

            # Workaround for httpx proxy issue in refinitiv.data v1.6.2
            # Clear proxy environment variables that cause TypeError in httpx
            import os
            for proxy_var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
                if proxy_var in os.environ:
                    del os.environ[proxy_var]

            app_key = get_provider_credential_sync("lseg", "app_key")
            username = get_provider_credential_sync("lseg", "username")
            password = get_provider_credential_sync("lseg", "password")

            session = rd.session.platform.Definition(
                app_key=app_key,
                grant=rd.session.platform.GrantPassword(
                    username=username,
                    password=password,
                ),
                signon_control=True
            ).get_session()

            logger.info("Session definition created, opening session...")
            open_output = self._open_session(session)
            if open_output:
                logger.warning("Refinitiv session open output: %s", open_output)
                self._raise_if_auth_error(open_output)

            if not self._is_session_open(session):
                raise ProviderConnectionError(
                    "LSEG session did not open successfully.",
                    details={"error": open_output or "Session open returned without an open session"},
                )

            logger.info("Session opened, setting as default...")
            rd.session.set_default(session)

            self._session = session
            self._session_created_at = datetime.now(UTC)
            logger.info("✅ Refinitiv session created successfully")

            # refinitiv.data creates its own plain-text StreamHandler on rd.* loggers
            # (lazy, after session open). Patch them to use our JSON formatter.
            from app.logging_config import patch_refinitiv_loggers
            patch_refinitiv_loggers()

        except ProviderConnectionError:
            raise
        except Exception as e:
            logger.error(f"❌ Failed to create Refinitiv session: {type(e).__name__}: {e}")
            self._raise_if_auth_error(str(e))
            raise ProviderConnectionError(
                "Could not authenticate with Refinitiv. Check LSEG credentials.",
                details={"hint": f"Auth error: {type(e).__name__}", "error": str(e)},
            )

    def _open_session(self, session: Any) -> str:
        """Open a Refinitiv session and return any output printed by the SDK."""
        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                session.open()
        except Exception as exc:
            output = "\n".join(part.strip() for part in (stdout.getvalue(), stderr.getvalue(), str(exc)) if part.strip())
            self._raise_if_auth_error(output)
            raise
        return "\n".join(part.strip() for part in (stdout.getvalue(), stderr.getvalue()) if part.strip())

    def _raise_if_auth_error(self, error_text: str) -> None:
        """Surface LSEG auth failures with their real message."""
        lowered = error_text.lower()
        if "access_denied" in lowered or "invalid username or password" in lowered:
            raise ProviderConnectionError(
                "LSEG authentication failed: Invalid username or password.",
                details={"error": error_text},
            )

    # ========================================================================
    # RIC Conversion with Caching
    # ========================================================================

    def _ticker_to_ric(self, ticker: str) -> str:
        """Convert ticker to RIC with 24h caching.

        Strategy: Try to find the equity (stock/ETF) version, not futures/options.
        """
        # Check cache
        if ticker in self._ric_cache:
            ric, cached_at = self._ric_cache[ticker]
            if datetime.now(UTC) - cached_at < self._ric_cache_ttl:
                logger.debug(f"RIC cache hit for {ticker}: {ric}")
                return ric

        # Try multiple search views/filters
        search_strategies = [
            # Strategy 1: EQUITY_QUOTES with TickerSymbol filter (may return futures/options)
            {
                "name": "EQUITY_QUOTES_WITH_FILTER",
                "view": search.Views.EQUITY_QUOTES,
                "filter": f"TickerSymbol eq '{ticker}'",
                "select": "RIC, DisplayName, TickerSymbol, ExchCode"
            },
            # Strategy 2: EQUITY_INSTRUMENTS with TickerSymbol filter
            {
                "name": "EQUITY_INSTRUMENTS_WITH_FILTER",
                "view": search.Views.EQUITY_INSTRUMENTS,
                "filter": f"TickerSymbol eq '{ticker}'",
                "select": "RIC, TickerSymbol"
            },
        ]

        for search_attempt in range(2):
            # Ensure session exists immediately before Refinitiv content calls.
            self._get_session()

            # Cache miss - search API with fallback strategies
            logger.debug(f"RIC cache miss for {ticker}, searching...")
            self._throttle()

            for strategy in search_strategies:
                try:
                    logger.debug(f"Trying RIC search strategy: {strategy['name']}")

                    definition_params = {
                        "query": ticker,
                        "view": strategy["view"],
                        "select": strategy["select"],
                        "top": 10  # Get more results to filter for non-futures/options
                    }

                    if strategy["filter"]:
                        definition_params["filter"] = strategy["filter"]

                    response = search.Definition(**definition_params).get_data()

                    if response.data.df is not None and not response.data.df.empty:
                        # Filter to prefer non-futures RICs (avoid 'c1', 'c2', etc. suffixes)
                        rics = response.data.df['RIC'].tolist()

                        # Prefer RICs without continuation/futures markers
                        for ric_val in rics:
                            ric_str = str(ric_val)
                            # Skip continuation contracts, options, and other derivatives
                            if not any(x in ric_str.lower() for x in ['c1', 'c2', 'c3', 'c4', 'p6.ba', 'call', 'put']):
                                self._ric_cache[ticker] = (ric_str, datetime.now(UTC))
                                logger.info(f"Ticker {ticker} mapped to RIC {ric_str} (strategy: {strategy['name']})")
                                return ric_str

                        # If no clean RIC found, use first one anyway (fallback)
                        ric_str = str(rics[0])
                        self._ric_cache[ticker] = (ric_str, datetime.now(UTC))
                        logger.warning(f"Ticker {ticker} mapped to RIC {ric_str} (no clean RIC, using first result)")
                        return ric_str

                except Exception as e:
                    logger.debug(f"Strategy {strategy['name']} failed: {e}")
                    if self._is_session_closed_error(e):
                        self._session = None
                        self._session_created_at = None
                        if search_attempt == 0:
                            logger.info(
                                f"RIC search hit closed LSEG session for {ticker}; refreshing session and retrying once"
                            )
                            break
                        raise ProviderConnectionError(
                            "LSEG session is not open. Retry the request after the session is refreshed.",
                            details={"error": str(e), "ticker": ticker},
                        )
                    continue

            if search_attempt == 0:
                logger.info(f"RIC search returned no results for {ticker}; refreshing LSEG session and retrying once")
                self._session = None
                self._session_created_at = None

        # All strategies failed
        logger.error(f"RIC search failed for {ticker} after {len(search_strategies)} strategies")
        raise DataNotFoundError("Ticker", ticker,
            details={"reason": "No RIC found for ticker", "ticker": ticker})

    def _is_session_closed_error(self, error: Exception) -> bool:
        """Detect Refinitiv errors caused by requests on a closed session."""
        return "session is not opened" in str(error).lower()

    # ========================================================================
    # Rate Limiting & Throttling
    # ========================================================================

    def _throttle(self) -> None:
        """Ensure rate limit is respected."""
        now = time.time()

        # Remove timestamps older than 1 second
        while self._request_times and now - self._request_times[0] > 1.0:
            self._request_times.popleft()

        # If at rate limit, wait
        if len(self._request_times) >= settings.LSEG_RATE_LIMIT_PER_SEC:
            sleep_time = 1.0 - (now - self._request_times[0])
            if sleep_time > 0:
                logger.debug(f"Rate limit reached, sleeping {sleep_time:.2f}s")
                time.sleep(sleep_time)

        self._request_times.append(time.time())

    # ========================================================================
    # Quote Caching
    # ========================================================================

    def _get_cached_quote(self, symbol: str) -> PriceQuote | None:
        """Get cached quote if still valid."""
        if settings.LSEG_CACHE_TTL_SECONDS <= 0:
            return None

        if symbol in self._quote_cache:
            quote, cached_at = self._quote_cache[symbol]
            age = (datetime.now(UTC) - cached_at).total_seconds()

            if age < settings.LSEG_CACHE_TTL_SECONDS:
                logger.debug(f"Cache hit for {symbol} (age: {age:.1f}s)")
                return quote

        return None

    def _cache_quote(self, symbol: str, quote: PriceQuote) -> None:
        """Cache quote data."""
        if settings.LSEG_CACHE_TTL_SECONDS > 0:
            self._quote_cache[symbol] = (quote, datetime.now(UTC))

    # ========================================================================
    # Retry Logic with Exponential Backoff
    # ========================================================================

    def _retry_with_backoff(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Execute function with retry logic and exponential backoff."""
        max_retries = 3
        base_delay = 1.0

        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # Check if retryable error
                if not self._is_retryable_error(e):
                    raise

                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    logger.error(f"All {max_retries} attempts failed")
                    raise ProviderConnectionError(
                        f"Refinitiv API failed after {max_retries} retries",
                        details={"error": str(e), "attempts": max_retries}
                    )
        raise RuntimeError("Unreachable")

    def _is_retryable_error(self, error: Exception) -> bool:
        """Check if error should trigger retry."""
        error_str = str(error).lower()

        # DO NOT retry on data availability errors
        non_retryable_keywords = [
            "no data to return",
            "system cannot return data",
            "not found",
            "no such",
            "unknown",
            "invalid ric"
        ]
        if any(keyword in error_str for keyword in non_retryable_keywords):
            return False

        # Retry on connection, timeout, rate limit, server errors
        return any(keyword in error_str for keyword in [
            "timeout", "connection", "429", "500", "502", "503"
        ])



    # ========================================================================
    # Data Validation & Extraction
    # ========================================================================

    def _validate_and_extract(self, df: pd.DataFrame, symbol: str) -> PriceQuote:
        """Extract and validate quote data from DataFrame."""
        if df is None or df.empty:
            raise DataNotFoundError("Quote", symbol)

        row = df.iloc[0]

        # Extract fields with safe handling
        def safe_decimal(field_name: str, required: bool = False) -> Decimal | None:
            if field_name not in df.columns:
                if required and settings.LSEG_STRICT_VALIDATION:
                    raise DataValidationError(
                        f"Required field '{field_name}' missing for {symbol}"
                    )
                return None

            value = row[field_name]
            if pd.isna(value):
                if required and settings.LSEG_STRICT_VALIDATION:
                    raise DataValidationError(
                        f"Required field '{field_name}' is NaN for {symbol}"
                    )
                return None

            return Decimal(str(value))

        # Build PriceQuote
        # Fields from historical_pricing: TRDPRC_1, OPEN_PRC, HIGH_1, LOW_1, BID, ASK, ACVOL_UNS, VWAP
        price = safe_decimal("TRDPRC_1", required=True)
        if price is None:
            price = Decimal(0)

        return PriceQuote(
            symbol=symbol,
            price=price,  # Last trade price from historical data
            currency="USD",  # Refinitiv returns USD prices
            provider="lseg",
            bid=safe_decimal("BID"),
            ask=safe_decimal("ASK"),
            open=safe_decimal("OPEN_PRC"),
            high=safe_decimal("HIGH_1"),
            low=safe_decimal("LOW_1"),
            volume=int(row["ACVOL_UNS"]) if "ACVOL_UNS" in df.columns and pd.notna(row["ACVOL_UNS"]) else None,
            timestamp=datetime.now(UTC)
        )

    # ========================================================================
    # Price Provider Methods (BasePriceProvider)
    # ========================================================================

    async def get_last_price(self, symbol: str, market_data_type: int | None = None, sec_type: str = "stock") -> PriceQuote:
        """Get current price quote for a symbol.

        Note: LSEG uses historical pricing summaries (daily) and does not support
        IBKR-style market data types. The `market_data_type` and `sec_type` parameters
        are accepted for interface compatibility but are ignored.
        """
        # Log only if caller passed a market_data_type to make behavior explicit
        if market_data_type is not None:
            logger.info(
                f"LSEGProvider: market_data_type={market_data_type} is ignored; using historical summaries (daily)."
            )
        # Check cache first
        cached = self._get_cached_quote(symbol)
        if cached:
            return cached

        # Convert ticker to RIC
        ric = self._ticker_to_ric(symbol)

        # Fetch quote using historical_pricing (like test_connect.py does)
        def fetch_quote() -> Any:
            self._get_session()
            self._throttle()

            # Use historical_pricing to get the most recent bar
            response = historical_pricing.summaries.Definition(
                universe=ric,
                interval=historical_pricing.Intervals.DAILY,
                count=1  # Get most recent day
            ).get_data()

            if response.data.df is None or response.data.df.empty:
                raise DataNotFoundError("Quote", symbol,
                    details={"ric": ric, "reason": "No historical data returned"})

            return response.data.df

        df = self._retry_with_backoff(fetch_quote)
        quote = self._validate_and_extract(df, symbol)

        # Cache result
        self._cache_quote(symbol, quote)

        return quote

    async def get_historical_prices(self, symbol: str, interval: str, start: datetime, end: datetime, extended_hours: bool = False, sec_type: str = "STK") -> list[PriceBar]:
        """
        Get historical price bars for a symbol.

        Note:
            - sec_type is ignored (LSEG handles stocks and indices via RIC lookup)
            - Intraday intervals (1m, 5m, etc.) limited to ~20 trading days max
            - Very old intraday data (>2 years) may not be available; use daily intervals
        """
        # Ensure start/end are timezone-aware (convert naive to UTC)
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)

        # Convert ticker to RIC
        ric = self._ticker_to_ric(symbol)

        # Map interval to Refinitiv format
        refinitiv_interval = self._map_interval(interval)

        # Validate intraday requests - LSEG has limitations
        duration = end - start
        is_intraday = interval in ["1m", "5m", "15m", "30m", "1h"]

        if is_intraday:
            # Check if request is too old for intraday
            if duration.days > 365 * 2:  # >2 years
                logger.warning(
                    f"Intraday interval {interval} requested for {duration.days} days (>2 years). "
                    f"LSEG may not have this historical data. Consider using daily interval."
                )

            # Warn if requesting too many intraday bars at once
            estimated_bars = min(1000, duration.days * 390)
            if estimated_bars > 500:
                logger.warning(
                    f"Large intraday request: ~{estimated_bars} bars for {duration.days} days. "
                    f"This may exceed LSEG limits. Consider shorter date ranges."
                )

        # Calculate number of bars needed
        if interval == "1d":
            count = duration.days + 1
        elif interval == "1w":
            count = duration.days // 7 + 1
        elif is_intraday:
            # For intraday, cap at 1000 bars (LSEG limitation)
            count = min(1000, duration.days * 390)
        else:
            count = 100  # Default

        logger.debug(f"LSEG historical request: RIC={ric}, interval={interval}, count={count}, duration={duration.days}d")

        # Fetch historical data with retry
        def fetch_historical() -> Any:
            self._get_session()
            self._throttle()

            # Format dates for LSEG (YYYY-MM-DD for daily, full ISO for intraday)
            # Summaries Definition supports start and end strings
            start_str = start.strftime("%Y-%m-%d") if interval == "1d" else start.isoformat()
            end_str = end.strftime("%Y-%m-%d") if interval == "1d" else end.isoformat()

            kwargs = {
                "universe": ric,
                "interval": refinitiv_interval,
                "start": start_str,
                "end": end_str
            }
            
            if not extended_hours and is_intraday:
                kwargs["sessions"] = [
                    historical_pricing.Sessions.NORMAL
                ]

            response = historical_pricing.summaries.Definition(**kwargs).get_data()

            if response.data.df is None or response.data.df.empty:
                raise DataNotFoundError("Historical data", symbol,
                    details={
                        "ric": ric,
                        "interval": interval,
                        "duration_days": duration.days,
                        "note": "LSEG limitation: intraday data only available for ~2 years; very old data needs daily interval"
                    })

            return response.data.df

        try:
            df = self._retry_with_backoff(fetch_historical)
        except ProviderConnectionError as e:
            # Re-wrap connection errors with data availability context
            error_msg = str(e).lower()
            if "system cannot return data" in error_msg or "no data to return" in error_msg:
                raise DataNotFoundError(
                    "Historical data",
                    f"{symbol} ({interval}, {duration.days}d)",
                    details={
                        "ric": ric,
                        "interval": interval,
                        "duration_days": duration.days,
                        "reason": "Data not available in LSEG archives",
                        "suggestions": [
                            "Try a shorter date range",
                            "Use daily interval instead of intraday for data >2 years old",
                            "Try more recent dates (last 2 years typically available)",
                        ]
                    }
                )
            raise
        except Exception as e:
            # Catch any other RDError or exception from LSEG
            error_msg = str(e).lower()
            if "system cannot return data" in error_msg or "no data" in error_msg:
                raise DataNotFoundError(
                    "Historical data",
                    f"{symbol} ({interval}, {duration.days}d)",
                    details={
                        "ric": ric,
                        "interval": interval,
                        "duration_days": duration.days,
                        "reason": "Data not available in LSEG archives",
                        "suggestions": [
                            "Try a shorter date range",
                            "Use daily interval instead of intraday for data >2 years old",
                            "Try more recent dates (last 2 years typically available)",
                        ],
                        "original_error": str(e)
                    }
                )
            raise

        # Convert DataFrame to PriceBar list
        bars = []
        for idx, row in df.iterrows():
            try:
                # Parse timestamp from index (row.name is the date index)
                timestamp = pd.to_datetime(row.name if hasattr(row, 'name') else idx).to_pydatetime()
                # Make timezone-aware if naive
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=UTC)

                # Historical pricing columns: TRDPRC_1, OPEN_PRC, HIGH_1, LOW_1, ACVOL_UNS
                bar = PriceBar(
                    symbol=symbol,
                    start=timestamp,
                    end=timestamp,
                    open=Decimal(str(row['OPEN_PRC'])) if 'OPEN_PRC' in df.columns and pd.notna(row['OPEN_PRC']) else Decimal(0),
                    high=Decimal(str(row['HIGH_1'])) if 'HIGH_1' in df.columns and pd.notna(row['HIGH_1']) else Decimal(0),
                    low=Decimal(str(row['LOW_1'])) if 'LOW_1' in df.columns and pd.notna(row['LOW_1']) else Decimal(0),
                    close=Decimal(str(row['TRDPRC_1'])) if 'TRDPRC_1' in df.columns and pd.notna(row['TRDPRC_1']) else Decimal(0),
                    volume=int(row['ACVOL_UNS']) if 'ACVOL_UNS' in df.columns and pd.notna(row['ACVOL_UNS']) else 0,
                    provider="lseg"
                )
                bars.append(bar)
            except Exception as e:
                logger.warning(f"Skipping bar due to error: {e}")
                continue

        # Filter by date range
        bars = [bar for bar in bars if start <= bar.start <= end]

        return bars

    def _map_interval(self, interval: str) -> Any:
        """Map API interval to Refinitiv Intervals enum."""
        mapping = {
            "1m": historical_pricing.Intervals.MINUTE,
            "2m": historical_pricing.Intervals.MINUTE,  # Fetch 1min, caller can resample
            "5m": historical_pricing.Intervals.FIVE_MINUTES,
            "15m": historical_pricing.Intervals.TEN_MINUTES,  # Use TEN_MINUTES as closest
            "30m": historical_pricing.Intervals.THIRTY_MINUTES,
            "1h": historical_pricing.Intervals.HOURLY,
            "1d": historical_pricing.Intervals.DAILY,
            "1w": historical_pricing.Intervals.WEEKLY
        }
        if interval not in mapping:
            raise ProviderError(
                f"Unsupported interval '{interval}' for LSEG provider.",
                details={"supported_intervals": list(mapping.keys())}
            )
        return mapping[interval]

    # ========================================================================
    # Company Provider Methods (BaseCompanyProvider) - Stub for now
    # ========================================================================

    async def get_company_profile(self, symbol: str) -> CompanyProfile:
        # TODO: Replace with real API call
        if symbol.upper() == "UNKNOWN":
            raise DataNotFoundError("Company", symbol)

        return CompanyProfile(
            symbol=symbol,
            name=f"{symbol} Corp",
            description="A leading technology company.",
            exchange="NASDAQ",
            currency="USD",
            website=cast(Any, "https://example.com"),
            sector="Technology",
            industry="Consumer Electronics",
            employees=150000,
            provider="lseg"
        )

    async def search_companies(self, query: str) -> list[CompanySummary]:
        # TODO: Replace with real API call
        return [
            CompanySummary(
                symbol=query.upper(),
                name=f"{query.capitalize()} Inc.",
                exchange="NASDAQ",
                sector="Technology",
                provider="lseg"
            ),
            CompanySummary(
                symbol=f"{query.upper()}B",
                name=f"{query.capitalize()} Class B",
                exchange="NYSE",
                sector="Technology",
                provider="lseg"
            )
        ]

    # ========================================================================
    # News Provider Methods (BaseNewsProvider)
    # ========================================================================

    async def get_company_news(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
        limit: int = 20,
        offset: int = 0,
        language: str = "en",
        category: str | None = None
    ) -> list[NewsArticle]:
        """Get news articles for a company from LSEG."""
        try:
            # 1. Convert ticker to RIC
            ric = self._ticker_to_ric(symbol)
            if not ric:
                raise DataNotFoundError("Ticker", symbol)

            # 2. Fetch news headlines using Refinitiv Data Library
            # Use rd.news.get_headlines() with RIC query
            df = rd.news.get_headlines(
                query=f"R:{ric}",
                count=limit + offset,
                start=f"{from_date.isoformat()}T00:00:00",
                end=f"{to_date.isoformat()}T23:59:59"
            )

            # 3. Check response validity
            if df is None or df.empty:
                return []

            # 4. Apply offset and limit
            if offset > 0:
                df = df.iloc[offset:]
            df = df.head(limit)

            # 5. Parse articles from DataFrame
            articles = []
            for _, row in df.iterrows():
                # Extract basic fields
                article_id = f"lseg:{row.get('storyId', '')}"
                title = row.get('headline', 'No title')
                published_at = pd.to_datetime(row.get('versionCreated'))
                source = row.get('sourceCode', 'LSEG')
                url = row.get('storyUrl', '')

                # 6. Map LSEG subjects to categories
                subjects = row.get('subjects', [])
                category_map = {
                    'EARN': 'earnings',
                    'M&A': 'merger',
                    'PROD': 'product',
                    'REG': 'legal'
                }
                article_category = None
                if isinstance(subjects, list):
                    for subj in subjects:
                        if subj in category_map:
                            article_category = category_map[subj]
                            break

                # 7. Apply category filter
                if category and article_category != category:
                    continue

                # 8. Create article object (full_text is optional for LSEG)
                articles.append(NewsArticle(
                    article_id=article_id,
                    title=title,
                    summary=row.get('firstParagraph', title),
                    published_at=published_at,
                    source=source,
                    url=url,
                    full_text=None,  # Full text requires separate API call
                    category=article_category,
                    image=None,
                    sentiment=None
                ))

            return articles

        except DataNotFoundError:
            raise
        except Exception as e:
            logger.error(f"LSEG news error for {symbol}: {e}")
            raise ProviderError(f"Failed to fetch news from LSEG: {e!s}")
