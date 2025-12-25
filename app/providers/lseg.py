from datetime import datetime, timedelta, timezone, date
from typing import List, Optional, Dict, Tuple, TypeVar, Callable, Literal
from decimal import Decimal
from collections import deque
import time
import math
import logging
import pandas as pd

from app.config import settings
from app.models.company import CompanyProfile, CompanySummary
from app.models.price import PriceQuote, PriceBar
from app.models.options import OptionChain, OptionQuote
from app.providers.base import BaseCompanyProvider, BasePriceProvider, BaseOptionsProvider
from app.utils.errors import DataNotFoundError, ProviderConnectionError, DataValidationError, ProviderError

logger = logging.getLogger(__name__)

# Lazy import refinitiv to avoid import errors if not installed
try:
    import refinitiv.data as rd
    from refinitiv.data.content import search, historical_pricing, pricing
    REFINITIV_AVAILABLE = True
except ImportError:
    REFINITIV_AVAILABLE = False
    logger.warning("refinitiv.data not available - LSEG provider will not work")

T = TypeVar('T')


class LSEGProvider(BaseCompanyProvider, BasePriceProvider, BaseOptionsProvider):
    """Refinitiv (LSEG) provider for stock prices, company data, and options."""

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

            logger.info(f"Session definition created, opening session...")
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
    # Quantitative Analytics Fallback (Black-Scholes)
    # ========================================================================

    def _norm_cdf(self, x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    def _norm_pdf(self, x: float) -> float:
        return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)

    def _bs_price(self, S: float, K: float, r: float, q: float, sigma: float, T: float, is_call: bool) -> float:
        if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
            return max(0.0, (S - K) if is_call else (K - S))
        d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        if is_call:
            return S * math.exp(-q * T) * self._norm_cdf(d1) - K * math.exp(-r * T) * self._norm_cdf(d2)
        else:
            return K * math.exp(-r * T) * self._norm_cdf(-d2) - S * math.exp(-q * T) * self._norm_cdf(-d1)

    def _bs_greeks(self, S: float, K: float, r: float, q: float, sigma: float, T: float, is_call: bool):
        if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
            return None, None, None, None
        d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        pdf_d1 = self._norm_pdf(d1)
        delta = math.exp(-q * T) * (self._norm_cdf(d1) if is_call else (self._norm_cdf(d1) - 1.0))
        gamma = (math.exp(-q * T) * pdf_d1) / (S * sigma * math.sqrt(T))
        vega = S * math.exp(-q * T) * pdf_d1 * math.sqrt(T)
        theta_call = (
            - (S * math.exp(-q * T) * pdf_d1 * sigma) / (2.0 * math.sqrt(T))
            - r * K * math.exp(-r * T) * self._norm_cdf(d2)
            + q * S * math.exp(-q * T) * self._norm_cdf(d1)
        )
        theta_put = (
            - (S * math.exp(-q * T) * pdf_d1 * sigma) / (2.0 * math.sqrt(T))
            + r * K * math.exp(-r * T) * self._norm_cdf(-d2)
            - q * S * math.exp(-q * T) * self._norm_cdf(-d1)
        )
        theta = theta_call if is_call else theta_put
        return delta, gamma, vega, theta

    def _solve_iv(self, S: float, K: float, r: float, q: float, T: float, is_call: bool, target_price: float) -> Optional[float]:
        if target_price <= 0 or S <= 0 or K <= 0 or T <= 0:
            return None
        lo, hi = 1e-4, 5.0
        for _ in range(40):
            mid = 0.5 * (lo + hi)
            price = self._bs_price(S, K, r, q, mid, T, is_call)
            if price > target_price:
                hi = mid
            else:
                lo = mid
        iv = 0.5 * (lo + hi)
        return iv if iv > 0 else None

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
    # Options Provider Methods (BaseOptionsProvider)
    # ========================================================================

    async def get_option_chain(
        self,
        symbol: str,
        expiry: date,
        min_strike: Optional[Decimal] = None,
        max_strike: Optional[Decimal] = None,
        right: Optional[Literal["call", "put"]] = None,
        include_level2: bool = False
    ) -> OptionChain:
        """Get option chain for a symbol and expiry using LSEG APIs.

        Strategy:
        1) Convert ticker to underlying RIC
        2) Use rd.discover.chain_expansion(universe=RIC) to retrieve option contracts
        3) Filter contracts by expiry and strike (and right if provided)
        4) Fetch quotes per option RIC via EQUITY_DERIVATIVE_QUOTES
        """
        try:
            logger.info(f"Fetching option chain for {symbol} expiry {expiry} via LSEG")
            self._get_session()
            self._throttle()

            # Step 1: Underlying RIC
            try:
                underlying_ric = self._ticker_to_ric(symbol)
                logger.debug(f"Underlying {symbol} -> RIC {underlying_ric}")
            except Exception as e:
                logger.warning(f"RIC lookup failed for {symbol}: {e}")
                return OptionChain(underlying_symbol=symbol, expiry=expiry, options=[], provider="lseg")

            # Step 2: Query quotes view directly filtered by ExpiryDate to collect option RICs
            expiry_iso = expiry.strftime('%Y-%m-%d')
            logger.debug(f"Searching EQUITY_DERIVATIVE_QUOTES for symbol={symbol}, ExpiryDate={expiry_iso}")
            try:
                quotes_resp = search.Definition(
                    view=search.Views.EQUITY_DERIVATIVE_QUOTES,
                    query=symbol,
                    filter=f"ExpiryDate eq {expiry_iso}",
                    select="RIC, DisplayName, StrikePrice, ExpiryDate, OptionType, BID, ASK, TRDPRC_1, IV, DELTA, GAMMA, VEGA, THETA, ACVOL_1, OPEN_INT",
                    top=1000
                ).get_data()
            except Exception as e:
                logger.error(f"Quotes search failed: {e}")
                return OptionChain(underlying_symbol=symbol, expiry=expiry, options=[], provider="lseg")

            dfq_all = getattr(quotes_resp.data, 'df', None)
            if dfq_all is None or dfq_all.empty:
                logger.info(f"No quotes found for {symbol} {expiry_iso}")
                return OptionChain(underlying_symbol=symbol, expiry=expiry, options=[], provider="lseg")
            logger.debug(f"Quotes search returned {len(dfq_all)} rows")

            # Build RIC list and static attributes (strike, right) from search view
            ric_static: Dict[str, Dict[str, object]] = {}
            dfq_by_ric: Dict[str, pd.Series] = {}
            options_data = []
            for _, row in dfq_all.iterrows():
                # Basic validations
                ric_val = row['RIC'] if 'RIC' in dfq_all.columns else None
                strike_val = row['StrikePrice'] if 'StrikePrice' in dfq_all.columns else None
                if pd.isna(strike_val):
                    continue
                try:
                    strike_dec = Decimal(str(strike_val))
                except Exception:
                    continue
                if min_strike and strike_dec < min_strike:
                    continue
                if max_strike and strike_dec > max_strike:
                    continue

                # Right filter
                opt_type = str(row['OptionType']).upper() if 'OptionType' in dfq_all.columns and pd.notna(row['OptionType']) else ''
                if right == 'call' and opt_type and 'C' not in opt_type:
                    continue
                if right == 'put' and opt_type and 'P' not in opt_type:
                    continue
                option_right = 'call' if ('C' in opt_type) else ('put' if ('P' in opt_type) else (right or 'call'))

                if ric_val and pd.notna(ric_val):
                    ric_static[str(ric_val)] = {
                        "strike": strike_dec,
                        "type": option_right
                    }
                    dfq_by_ric[str(ric_val)] = row

            # Limit RICs and fetch real-time snapshot via pricing API
            ric_list = list(ric_static.keys())
            ric_list = ric_list[:100]
            pricing_df = None
            try:
                self._throttle()
                snap = pricing.Definition(
                    universe=ric_list,
                    fields=[
                        'RIC','BID','ASK','TRDPRC_1','IMPVOL_1','DELTA','GAMMA','VEGA','THETA','ACVOL_1','OPEN_INT'
                    ]
                ).get_data()
                pricing_df = getattr(snap.data, 'df', None)
            except Exception as e:
                logger.warning(f"Pricing snapshot failed: {e}. Falling back to search data only.")

            # Step 3: Merge pricing snapshot (if available) and build OptionQuote list
            if pricing_df is not None and not pricing_df.empty:
                logger.debug(f"Pricing snapshot columns: {list(pricing_df.columns)}")
                for _, prow in pricing_df.iterrows():
                    ric = str(prow['RIC']) if 'RIC' in pricing_df.columns and pd.notna(prow['RIC']) else None
                    if not ric or ric not in ric_static:
                        continue
                    static = ric_static[ric]

                    # Price mid fallback
                    price = Decimal(str(prow['TRDPRC_1'])) if 'TRDPRC_1' in pricing_df.columns and pd.notna(prow['TRDPRC_1']) else None
                    bid = Decimal(str(prow['BID'])) if 'BID' in pricing_df.columns and pd.notna(prow['BID']) else None
                    ask = Decimal(str(prow['ASK'])) if 'ASK' in pricing_df.columns and pd.notna(prow['ASK']) else None
                    if price is None and bid is not None and ask is not None:
                        price = (bid + ask) / 2
                    if price is None:
                        price = Decimal('0')

                    iv = Decimal(str(prow['IMPVOL_1'])) if 'IMPVOL_1' in pricing_df.columns and pd.notna(prow['IMPVOL_1']) else None
                    delta = Decimal(str(prow['DELTA'])) if 'DELTA' in pricing_df.columns and pd.notna(prow['DELTA']) else None
                    gamma = Decimal(str(prow['GAMMA'])) if 'GAMMA' in pricing_df.columns and pd.notna(prow['GAMMA']) else None
                    vega = Decimal(str(prow['VEGA'])) if 'VEGA' in pricing_df.columns and pd.notna(prow['VEGA']) else None
                    theta = Decimal(str(prow['THETA'])) if 'THETA' in pricing_df.columns and pd.notna(prow['THETA']) else None

                    volume = None
                    if 'ACVOL_1' in pricing_df.columns and pd.notna(prow['ACVOL_1']):
                        try:
                            volume = int(prow['ACVOL_1'])
                        except Exception:
                            try:
                                volume = int(Decimal(str(prow['ACVOL_1'])))
                            except Exception:
                                volume = None

                    open_interest = None
                    if 'OPEN_INT' in pricing_df.columns and pd.notna(prow['OPEN_INT']):
                        try:
                            open_interest = int(prow['OPEN_INT'])
                        except Exception:
                            try:
                                open_interest = int(Decimal(str(prow['OPEN_INT'])))
                            except Exception:
                                open_interest = None

                    options_data.append(OptionQuote(
                        symbol=ric,
                        underlying_symbol=symbol,
                        strike=static['strike'],
                        expiry=expiry,
                        type=static['type'],
                        price=price,
                        bid=bid,
                        ask=ask,
                        volume=volume,
                        open_interest=open_interest,
                        implied_volatility=iv,
                        delta=delta,
                        gamma=gamma,
                        vega=vega,
                        theta=theta,
                        provider="lseg"
                    ))
            else:
                # Fallback: enrich with historical last price and compute IV/Greeks; pull BID/ASK if present in search view
                logger.debug("Pricing snapshot empty; falling back to historical pricing + computed Greeks")
                # Fetch underlying price once
                try:
                    underlying_quote = await self.get_last_price(symbol)
                    S_dec = underlying_quote.price or Decimal('0')
                except Exception:
                    S_dec = Decimal('0')
                S = float(S_dec) if S_dec is not None else 0.0
                # Risk-free and dividend assumptions
                r, q = 0.03, 0.0
                today = datetime.now(timezone.utc).date()

                count = 0
                for ric, static in ric_static.items():
                    if count >= 50:
                        break
                    count += 1
                    # Initialize per-option fields before fetching data
                    last_price = Decimal('0')
                    bid = None
                    ask = None
                    iv = None
                    delta = None
                    gamma = None
                    vega = None
                    theta = None
                    volume = None
                    open_interest = None
                    try:
                        self._throttle()
                        hresp = historical_pricing.summaries.Definition(
                            universe=ric,
                            interval=historical_pricing.Intervals.DAILY,
                            count=1,
                            fields=[
                                'TRDPRC_1','CLOSE','BID','ASK','ACVOL_UNS','ACVOL_1','OPEN_INT'
                            ]
                        ).get_data()
                        hdf = getattr(hresp.data, 'df', None)
                        if hdf is not None and not hdf.empty:
                            if 'TRDPRC_1' in hdf.columns and pd.notna(hdf['TRDPRC_1'].iloc[0]):
                                last_price = Decimal(str(hdf['TRDPRC_1'].iloc[0]))
                            elif 'CLOSE' in hdf.columns and pd.notna(hdf['CLOSE'].iloc[0]):
                                last_price = Decimal(str(hdf['CLOSE'].iloc[0]))
                            # Try to fill bid/ask and volume from historical summaries if present
                            if 'BID' in hdf.columns and pd.notna(hdf['BID'].iloc[0]):
                                bid = Decimal(str(hdf['BID'].iloc[0]))
                            if 'ASK' in hdf.columns and pd.notna(hdf['ASK'].iloc[0]):
                                ask = Decimal(str(hdf['ASK'].iloc[0]))
                            if 'ACVOL_UNS' in hdf.columns and pd.notna(hdf['ACVOL_UNS'].iloc[0]):
                                try:
                                    volume = int(hdf['ACVOL_UNS'].iloc[0])
                                except Exception:
                                    try:
                                        volume = int(Decimal(str(hdf['ACVOL_UNS'].iloc[0])))
                                    except Exception:
                                        volume = None
                            elif 'ACVOL_1' in hdf.columns and pd.notna(hdf['ACVOL_1'].iloc[0]):
                                try:
                                    volume = int(hdf['ACVOL_1'].iloc[0])
                                except Exception:
                                    try:
                                        volume = int(Decimal(str(hdf['ACVOL_1'].iloc[0])))
                                    except Exception:
                                        volume = None
                            if 'OPEN_INT' in hdf.columns and pd.notna(hdf['OPEN_INT'].iloc[0]):
                                try:
                                    open_interest = int(hdf['OPEN_INT'].iloc[0])
                                except Exception:
                                    try:
                                        open_interest = int(Decimal(str(hdf['OPEN_INT'].iloc[0])))
                                    except Exception:
                                        open_interest = None
                    except Exception:
                        pass

                    # Pull bid/ask and any direct analytics from search view row if available
                    row = dfq_by_ric.get(ric)
                    if row is not None:
                        if 'BID' in dfq_all.columns and pd.notna(row['BID']):
                            bid = Decimal(str(row['BID']))
                        if 'ASK' in dfq_all.columns and pd.notna(row['ASK']):
                            ask = Decimal(str(row['ASK']))
                        for iv_col in ['IV', 'IMPVOL_1', 'IMPLIED_VOLATILITY']:
                            if iv is None and iv_col in dfq_all.columns and pd.notna(row[iv_col]):
                                iv = Decimal(str(row[iv_col]))
                        def _dec(names):
                            for c in names:
                                if c in dfq_all.columns and pd.notna(row[c]):
                                    try:
                                        return Decimal(str(row[c]))
                                    except Exception:
                                        continue
                            return None
                        if delta is None:
                            delta = _dec(['DELTA', 'GREEK_DELTA'])
                        if gamma is None:
                            gamma = _dec(['GAMMA', 'GREEK_GAMMA'])
                        if vega is None:
                            vega = _dec(['VEGA', 'GREEK_VEGA'])
                        if theta is None:
                            theta = _dec(['THETA', 'GREEK_THETA'])
                        # Volume & Open Interest from search rows if available
                        if volume is None:
                            for vol_col in ['ACVOL_1', 'ACVOL', 'VOLUME']:
                                if vol_col in dfq_all.columns and pd.notna(row[vol_col]):
                                    try:
                                        volume = int(row[vol_col])
                                    except Exception:
                                        try:
                                            volume = int(Decimal(str(row[vol_col])))
                                        except Exception:
                                            volume = None
                                    break
                        if open_interest is None:
                            for oi_col in ['OPEN_INT', 'OpenInterest']:
                                if oi_col in dfq_all.columns and pd.notna(row[oi_col]):
                                    try:
                                        open_interest = int(row[oi_col])
                                    except Exception:
                                        try:
                                            open_interest = int(Decimal(str(row[oi_col])))
                                        except Exception:
                                            open_interest = None
                                    break

                    # If still missing IV/Greeks, compute using Black-Scholes with solved IV from last price
                    try:
                        K = float(static['strike'])
                        T = max(0.0, (expiry - today).days / 365.0)
                        is_call = True if static['type'] == 'call' else False
                        target = float(last_price)
                        if iv is None and target > 0 and S > 0 and K > 0 and T > 0:
                            iv_val = self._solve_iv(S, K, r, q, T, is_call, target)
                            if iv_val:
                                iv = Decimal(str(iv_val))
                                d, g, v, t = self._bs_greeks(S, K, r, q, iv_val, T, is_call)
                                if d is not None:
                                    delta = Decimal(str(d))
                                if g is not None:
                                    gamma = Decimal(str(g))
                                if v is not None:
                                    vega = Decimal(str(v))
                                if t is not None:
                                    theta = Decimal(str(t))
                    except Exception:
                        pass

                    options_data.append(OptionQuote(
                        symbol=ric,
                        underlying_symbol=symbol,
                        strike=static['strike'],
                        expiry=expiry,
                        type=static['type'],
                        price=last_price,
                        bid=bid,
                        ask=ask,
                        volume=volume,
                        open_interest=open_interest,
                        implied_volatility=iv,
                        delta=delta,
                        gamma=gamma,
                        vega=vega,
                        theta=theta,
                        provider="lseg"
                    ))

            logger.info(f"Retrieved {len(options_data)} options for {symbol} expiry {expiry}")
            return OptionChain(
                underlying_symbol=symbol,
                expiry=expiry,
                options=options_data,
                provider="lseg"
            )

        except Exception as e:
            logger.error(f"Error getting option chain for {symbol}: {e}")
            raise ProviderError(f"LSEG error: {e}")

    async def get_option_quote(
        self,
        symbol: str,
        option_id: str,
        include_level2: bool = False
    ) -> OptionQuote:
        """Get option quote for a specific option using LSEG EQUITY_DERIVATIVE_QUOTES.

        Args:
            symbol: Underlying symbol (e.g., 'AAPL')
            option_id: Option RIC or display name (e.g., 'AAPL  251226C00280000')
            include_level2: Include level 2 data (Greeks, etc.)

        Returns:
            OptionQuote with price and Greeks data
        """
        try:
            logger.info(f"Fetching option quote for {option_id} ({symbol})")
            self._get_session()
            self._throttle()

            # Query EQUITY_DERIVATIVE_QUOTES for this specific option
            response = search.Definition(
                view=search.Views.EQUITY_DERIVATIVE_QUOTES,
                query=option_id,
                select="RIC, DisplayName, StrikePrice, ExpiryDate, OptionType, BID, ASK, TRDPRC_1, IV, DELTA, GAMMA, VEGA, THETA, ACVOL_1, OPEN_INT",
                top=1
            ).get_data()

            if response.data.df is None or response.data.df.empty:
                raise DataNotFoundError("Option", option_id,
                    details={"reason": "Option not found in LSEG", "symbol": symbol})

            row = response.data.df.iloc[0]

            # Extract data
            underlying_symbol = symbol
            strike = Decimal(str(row['StrikePrice'])) if pd.notna(row['StrikePrice']) else Decimal('0')
            expiry_str = str(row['ExpiryDate']) if pd.notna(row['ExpiryDate']) else None
            expiry = datetime.strptime(expiry_str, '%Y-%m-%d').date() if expiry_str else date.today()

            option_type_str = str(row['OptionType']).upper() if pd.notna(row['OptionType']) else "C"
            is_call = 'C' in option_type_str
            option_right = "call" if is_call else "put"

            # Price (try last trade price first, then mid-market)
            price = None
            if 'TRDPRC_1' in response.data.df.columns and pd.notna(row['TRDPRC_1']):
                price = Decimal(str(row['TRDPRC_1']))
            if price is None and 'BID' in response.data.df.columns and 'ASK' in response.data.df.columns:
                bid = Decimal(str(row['BID'])) if pd.notna(row['BID']) else None
                ask = Decimal(str(row['ASK'])) if pd.notna(row['ASK']) else None
                if bid and ask:
                    price = (bid + ask) / 2
            if price is None:
                price = Decimal('0')

            # Greeks
            iv = Decimal(str(row['IV'])) if 'IV' in response.data.df.columns and pd.notna(row['IV']) else None
            delta = Decimal(str(row['DELTA'])) if 'DELTA' in response.data.df.columns and pd.notna(row['DELTA']) else None
            gamma = Decimal(str(row['GAMMA'])) if 'GAMMA' in response.data.df.columns and pd.notna(row['GAMMA']) else None
            vega = Decimal(str(row['VEGA'])) if 'VEGA' in response.data.df.columns and pd.notna(row['VEGA']) else None
            theta = Decimal(str(row['THETA'])) if 'THETA' in response.data.df.columns and pd.notna(row['THETA']) else None

            return OptionQuote(
                symbol=option_id,
                underlying_symbol=underlying_symbol,
                strike=strike,
                expiry=expiry,
                type=option_right,
                price=price,
                bid=Decimal(str(row['BID'])) if 'BID' in response.data.df.columns and pd.notna(row['BID']) else None,
                ask=Decimal(str(row['ASK'])) if 'ASK' in response.data.df.columns and pd.notna(row['ASK']) else None,
                volume=None,
                implied_volatility=iv,
                delta=delta,
                gamma=gamma,
                vega=vega,
                theta=theta,
                provider="lseg"
            )

        except DataNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error getting option quote for {option_id}: {e}")
            raise ProviderError(f"LSEG error: {e}")
