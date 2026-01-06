from datetime import datetime, timedelta, timezone, date
from typing import List, Optional, Dict, Tuple, TypeVar, Callable
from decimal import Decimal
from collections import deque
import time
import logging
import pandas as pd

from app.config import settings
from app.models.company import CompanyProfile, CompanySummary
from app.models.price import PriceQuote, PriceBar
from app.models.news import NewsArticle
from app.providers.base import BaseCompanyProvider, BasePriceProvider, BaseNewsProvider
from app.utils.errors import DataNotFoundError, ProviderConnectionError, DataValidationError, ProviderError

logger = logging.getLogger(__name__)

# Lazy import refinitiv to avoid import errors if not installed
try:
    import refinitiv.data as rd
    from refinitiv.data.content import search, historical_pricing
    REFINITIV_AVAILABLE = True
except ImportError:
    REFINITIV_AVAILABLE = False
    logger.warning("refinitiv.data not available - LSEG provider will not work")

T = TypeVar('T')


class LSEGProvider(BaseCompanyProvider, BasePriceProvider, BaseNewsProvider):
    """Refinitiv (LSEG) provider for stock prices, company data, and news.

    ⚠️  Options NOT supported - use IBKR provider instead.
    LSEG subscription lacks 'trapi.data.pricing.read' scope required for real-time Greeks.
    """

    def __init__(self):
        if not REFINITIV_AVAILABLE:
            raise ImportError("refinitiv.data package is required for LSEG provider")

        # Session management
        self._session = None
        self._session_created_at: Optional[datetime] = None
        self._session_ttl = timedelta(minutes=55)  # Refresh before 1h expiry

        # RIC conversion cache (ticker -> RIC mapping)
        self._ric_cache: Dict[str, Tuple[str, datetime]] = {}
        self._ric_cache_ttl = timedelta(hours=24)

        # Quote caching for performance
        self._quote_cache: Dict[str, Tuple[PriceQuote, datetime]] = {}

        # Rate limiting
        self._request_times: deque = deque(maxlen=settings.LSEG_RATE_LIMIT_PER_SEC)

        logger.info("LSEGProvider initialized")

    # ========================================================================
    # Session Management
    # ========================================================================

    def _get_session(self):
        """Get or create Refinitiv session with smart refresh."""
        now = datetime.now(timezone.utc)

        # Check if session needs refresh
        if self._session is None or self._session_created_at is None:
            logger.debug("Session is None or not created yet, creating new session...")
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

        return self._session

    def _create_session(self):
        """Create new Refinitiv session."""
        try:
            logger.info("Creating new Refinitiv session...")

            session = rd.session.platform.Definition(
                app_key=settings.LSEG_APP_KEY,
                grant=rd.session.platform.GrantPassword(
                    username=settings.LSEG_USERNAME,
                    password=settings.LSEG_PASSWORD
                ),
                signon_control=True
            ).get_session()

            logger.info("Session definition created, opening session...")
            session.open()

            logger.info("Session opened, setting as default...")
            rd.session.set_default(session)

            self._session = session
            self._session_created_at = datetime.now(timezone.utc)
            logger.info("✅ Refinitiv session created successfully")

        except Exception as e:
            logger.error(f"❌ Failed to create Refinitiv session: {type(e).__name__}: {e}")
            raise ProviderConnectionError(
                "Could not authenticate with Refinitiv",
                details={"error": str(e), "error_type": type(e).__name__}
            )

    # ========================================================================
    # RIC Conversion with Caching
    # ========================================================================

    def _ticker_to_ric(self, ticker: str) -> str:
        """Convert ticker to RIC with 24h caching."""
        # Check cache
        if ticker in self._ric_cache:
            ric, cached_at = self._ric_cache[ticker]
            if datetime.now(timezone.utc) - cached_at < self._ric_cache_ttl:
                logger.debug(f"RIC cache hit for {ticker}: {ric}")
                return ric

        # Ensure session exists
        self._get_session()

        # Cache miss - search API with fallback strategies
        logger.debug(f"RIC cache miss for {ticker}, searching...")
        self._throttle()

        # Try multiple search views/filters
        search_strategies = [
            # Strategy 1: EQUITY_QUOTES with TickerSymbol filter (most reliable - from test_connect.py)
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
            # Strategy 3: EQUITY_QUOTES query-only (no filter)
            {
                "name": "EQUITY_QUOTES",
                "view": search.Views.EQUITY_QUOTES,
                "filter": None,
                "select": "RIC, DisplayName"
            },
            # Strategy 4: EQUITY_INSTRUMENTS query-only (no filter)
            {
                "name": "EQUITY_INSTRUMENTS",
                "view": search.Views.EQUITY_INSTRUMENTS,
                "filter": None,
                "select": "RIC, TickerSymbol"
            }
        ]

        for strategy in search_strategies:
            try:
                logger.debug(f"Trying RIC search strategy: {strategy['name']}")

                definition_params = {
                    "query": ticker,
                    "view": strategy["view"],
                    "select": strategy["select"],
                    "top": 1
                }

                if strategy["filter"]:
                    definition_params["filter"] = strategy["filter"]

                response = search.Definition(**definition_params).get_data()

                if response.data.df is not None and not response.data.df.empty:
                    ric = response.data.df['RIC'].iloc[0]
                    self._ric_cache[ticker] = (ric, datetime.now(timezone.utc))
                    logger.info(f"Ticker {ticker} mapped to RIC {ric} (strategy: {strategy['name']})")
                    return ric

            except Exception as e:
                logger.debug(f"Strategy {strategy['name']} failed: {e}")
                continue

        # All strategies failed
        logger.error(f"RIC search failed for {ticker} after {len(search_strategies)} strategies")
        raise DataNotFoundError("Ticker", ticker,
            details={"reason": "No RIC found for ticker", "ticker": ticker})

    # ========================================================================
    # Rate Limiting & Throttling
    # ========================================================================

    def _throttle(self):
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

    def _get_cached_quote(self, symbol: str) -> Optional[PriceQuote]:
        """Get cached quote if still valid."""
        if settings.LSEG_CACHE_TTL_SECONDS <= 0:
            return None

        if symbol in self._quote_cache:
            quote, cached_at = self._quote_cache[symbol]
            age = (datetime.now(timezone.utc) - cached_at).total_seconds()

            if age < settings.LSEG_CACHE_TTL_SECONDS:
                logger.debug(f"Cache hit for {symbol} (age: {age:.1f}s)")
                return quote

        return None

    def _cache_quote(self, symbol: str, quote: PriceQuote):
        """Cache quote data."""
        if settings.LSEG_CACHE_TTL_SECONDS > 0:
            self._quote_cache[symbol] = (quote, datetime.now(timezone.utc))

    # ========================================================================
    # Retry Logic with Exponential Backoff
    # ========================================================================

    def _retry_with_backoff(self, func: Callable[..., T], *args, **kwargs) -> T:
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

    def _is_retryable_error(self, error: Exception) -> bool:
        """Check if error should trigger retry."""
        error_str = str(error).lower()
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
        def safe_decimal(field_name: str, required: bool = False) -> Optional[Decimal]:
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
        return PriceQuote(
            symbol=symbol,
            price=safe_decimal("TRDPRC_1", required=True),  # Last trade price from historical data
            currency="USD",  # Refinitiv returns USD prices
            provider="lseg",
            bid=safe_decimal("BID"),
            ask=safe_decimal("ASK"),
            volume=int(row["ACVOL_UNS"]) if "ACVOL_UNS" in df.columns and pd.notna(row["ACVOL_UNS"]) else None,
            timestamp=datetime.now(timezone.utc)
        )

    # ========================================================================
    # Price Provider Methods (BasePriceProvider)
    # ========================================================================

    async def get_last_price(self, symbol: str) -> PriceQuote:
        """Get current price quote for a symbol."""
        # Check cache first
        cached = self._get_cached_quote(symbol)
        if cached:
            return cached

        # Convert ticker to RIC
        ric = self._ticker_to_ric(symbol)

        # Fetch quote using historical_pricing (like test_connect.py does)
        def fetch_quote():
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

    async def get_historical_prices(self, symbol: str, interval: str, start: datetime, end: datetime) -> List[PriceBar]:
        """Get historical price bars for a symbol."""
        # Ensure start/end are timezone-aware (convert naive to UTC)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        # Convert ticker to RIC
        ric = self._ticker_to_ric(symbol)

        # Map interval to Refinitiv format
        refinitiv_interval = self._map_interval(interval)

        # Calculate number of bars needed
        duration = end - start
        if interval == "1d":
            count = duration.days + 1
        elif interval == "1w":
            count = duration.days // 7 + 1
        elif interval in ["1m", "5m", "15m", "30m", "1h"]:
            # For intraday, limit to reasonable count
            count = min(1000, duration.days * 390)  # ~390 minutes per trading day
        else:
            count = 100  # Default

        # Fetch historical data with retry
        def fetch_historical():
            self._get_session()
            self._throttle()

            response = historical_pricing.summaries.Definition(
                universe=ric,
                interval=refinitiv_interval,
                count=count
            ).get_data()

            if response.data.df is None or response.data.df.empty:
                raise DataNotFoundError("Historical data", symbol,
                    details={"ric": ric, "interval": interval})

            return response.data.df

        df = self._retry_with_backoff(fetch_historical)

        # Convert DataFrame to PriceBar list
        bars = []
        for idx, row in df.iterrows():
            try:
                # Parse timestamp from index (row.name is the date index)
                timestamp = pd.to_datetime(row.name if hasattr(row, 'name') else idx).to_pydatetime()
                # Make timezone-aware if naive
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)

                # Historical pricing columns: TRDPRC_1, OPEN_PRC, HIGH_1, LOW_1, ACVOL_UNS
                bar = PriceBar(
                    symbol=symbol,
                    start=timestamp,
                    end=timestamp,
                    open=Decimal(str(row['OPEN_PRC'])) if 'OPEN_PRC' in df.columns and pd.notna(row['OPEN_PRC']) else Decimal('0'),
                    high=Decimal(str(row['HIGH_1'])) if 'HIGH_1' in df.columns and pd.notna(row['HIGH_1']) else Decimal('0'),
                    low=Decimal(str(row['LOW_1'])) if 'LOW_1' in df.columns and pd.notna(row['LOW_1']) else Decimal('0'),
                    close=Decimal(str(row['TRDPRC_1'])) if 'TRDPRC_1' in df.columns and pd.notna(row['TRDPRC_1']) else Decimal('0'),
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

    def _map_interval(self, interval: str) -> str:
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
        return mapping.get(interval, historical_pricing.Intervals.DAILY)

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
            website="https://example.com",
            sector="Technology",
            industry="Consumer Electronics",
            employees=150000,
            provider="lseg"
        )

    async def search_companies(self, query: str) -> List[CompanySummary]:
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
        category: Optional[str] = None
    ) -> List[NewsArticle]:
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
                    category=article_category
                ))

            return articles

        except DataNotFoundError:
            raise
        except Exception as e:
            logger.error(f"LSEG news error for {symbol}: {e}")
            raise ProviderError(f"Failed to fetch news from LSEG: {str(e)}")
