import asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import List, Optional, Literal

from ib_async import IB, Stock, Option, Contract
from ib_async.objects import BarData

from app.config import settings
from app.models.price import PriceBar, PriceQuote
from app.models.options import OptionChain, OptionQuote
from app.models.company import CompanyProfile, CompanySummary
from app.models.news import NewsArticle
from app.providers.base import BasePriceProvider, BaseOptionsProvider, BaseCompanyProvider, BaseNewsProvider
from app.utils.errors import DataNotFoundError, ProviderConnectionError, ProviderError
import math
from app.utils.logging import logger

# Ensure event loop compatibility
# ib_async.util.patchAsyncio()

class IBKRProvider(BasePriceProvider, BaseOptionsProvider, BaseCompanyProvider, BaseNewsProvider):
    """Implementation for IBKR provider using ib_async."""

    async def _get_tickers_snapshot(self, contracts: List[Contract], skip_on_error: bool = True) -> List[object]:
        """
        Request market data snapshots for given contracts and wait for data.
        If skip_on_error is True, ignores subscription errors and returns available data.
        For options, uses streaming mode for better data quality.
        """
        logger.debug(f"Requesting market data snapshot for {len(contracts)} contracts")
        tickers = []
        failed_contracts = []

        # Determine if we're dealing with options
        is_option = any(c.secType == 'OPT' for c in contracts)
        snapshot_mode = not is_option  # Use streaming for options, snapshot for stocks

        logger.debug(f"Using {'streaming' if not snapshot_mode else 'snapshot'} mode for {len(contracts)} contracts")

        for c in contracts:
            try:
                ticker = self.ib.reqMktData(c, '', snapshot_mode, False)
                tickers.append(ticker)
            except Exception as e:
                error_msg = str(e)
                contract_info = f"{c.symbol} {c.strike if hasattr(c, 'strike') else 'N/A'}"

                if skip_on_error and self._handle_subscription_error(error_msg, contract_info):
                    # Only log warning for Level 1, debug for Level 2/3
                    if self._requested_market_data_type == 1:
                        logger.warning(f"Skipping contract due to subscription error: {c}")
                    else:
                        logger.debug(f"Skipping contract (subscription info): {c}")
                    failed_contracts.append(c)
                else:
                    raise

        # Wait for data (longer for options)
        timeout = 10.0 if is_option else 4.0
        start_wait = datetime.now()

        while (datetime.now() - start_wait).total_seconds() < timeout:
            # For options, check for bid/ask or close price
            if is_option:
                # Check for any valid market data indicator
                valid_count = sum(1 for t in tickers if
                    (self._is_valid(t.bid) and t.bid != -1) or
                    (self._is_valid(t.ask) and t.ask != -1) or
                    self._is_valid(t.last) or
                    self._is_valid(t.close))

                if valid_count > 0:
                    logger.debug(f"Got data for {valid_count}/{len(tickers)} option contracts")

                if valid_count >= max(1, len(tickers) * 0.5):  # At least 50% have data
                    break
            else:
                if all(t.time or t.last or t.close for t in tickers):
                    break
            await asyncio.sleep(0.5)

        # Cancel streaming subscriptions if we used them
        if not snapshot_mode:
            logger.debug(f"Cancelling {len(tickers)} streaming subscriptions")
            for t in tickers:
                self.ib.cancelMktData(t.contract)

        # Check if Level 1 subscription error occurred
        if self._level1_subscription_error:
            error_details = self._subscription_errors[-1] if self._subscription_errors else {}
            self._level1_subscription_error = False  # Reset flag
            raise ProviderError(
                "Level 1 (Live) market data requires additional subscription. "
                "Please check 'Market Data Connections' in TWS/Gateway settings or use market_data_type=2 or 3.",
                details=error_details,
                code="PROVIDER_NOT_AVAILABLE"
            )

        if failed_contracts:
            # Only log warning for Level 1, debug for Level 2/3
            if self._requested_market_data_type == 1:
                logger.warning(f"Failed to get data for {len(failed_contracts)} contracts due to subscription issues")
            else:
                logger.debug(f"Skipped {len(failed_contracts)} contracts (subscription not available for delayed data)")

        valid_tickers = [t for t in tickers if t.time or t.last or t.close or self._is_valid(t.bid)]
        logger.debug(f"Snapshot complete. Got data for {len(valid_tickers)}/{len(tickers)} contracts")
        return tickers

    def __init__(self):
        self.ib = IB()
        self.host = settings.IBKR_HOST
        self.port = settings.IBKR_PORT
        self.client_id = settings.IBKR_CLIENT_ID
        self.connect_on_request = settings.IBKR_CONNECT_ON_REQUEST
        self.market_data_type = settings.IBKR_MARKET_DATA_TYPE
        self.fallback_on_subscription_error = settings.IBKR_FALLBACK_ON_SUBSCRIPTION_ERROR

        # Keep track if we are currently connected implementation-wise
        self._connected = False

        # Track subscription errors
        self._subscription_errors = []

        # Track explicitly requested market data type (None = using default)
        self._requested_market_data_type = None

        # Track if Level 1 subscription error occurred (for strict failure)
        self._level1_subscription_error = False

    def _is_valid(self, val) -> bool:
        return val is not None and not (isinstance(val, float) and math.isnan(val))

    def _to_decimal(self, val) -> Optional[Decimal]:
        if self._is_valid(val):
            return Decimal(str(val))
        return None

    def _extract_greeks(self, ticker) -> dict:
        """Extract Greeks from ticker.modelGreeks if available."""
        greeks = {
            "implied_volatility": None,
            "delta": None,
            "gamma": None,
            "vega": None,
            "theta": None
        }

        if ticker.modelGreeks:
            mg = ticker.modelGreeks
            if self._is_valid(mg.impliedVol):
                greeks["implied_volatility"] = Decimal(str(mg.impliedVol))
            if self._is_valid(mg.delta):
                greeks["delta"] = Decimal(str(mg.delta))
            if self._is_valid(mg.gamma):
                greeks["gamma"] = Decimal(str(mg.gamma))
            if self._is_valid(mg.vega):
                greeks["vega"] = Decimal(str(mg.vega))
            if self._is_valid(mg.theta):
                greeks["theta"] = Decimal(str(mg.theta))

        return greeks

    async def _ensure_connection(self):
        """Ensure we have an active connection to IBKR."""
        if self.ib.isConnected():
            return

        try:
            logger.info(f"Connecting to IBKR at {self.host}:{self.port} (Client ID: {self.client_id})")
            await self.ib.connectAsync(self.host, self.port, self.client_id)
            self.ib.reqMarketDataType(self.market_data_type)

            # Install error handler to catch subscription warnings
            self.ib.errorEvent += self._on_ib_error

            self._connected = True
        except Exception as e:
            logger.error(f"Failed to connect to IBKR: {e}")
            raise ProviderConnectionError(f"Could not connect to IBKR: {str(e)}")
        else:
            logger.debug("Successfully connected to IBKR")

    def _on_ib_error(self, reqId, errorCode, errorString, contract):
        """
        Handle IBKR errors/warnings.
        Error 10089/10091 are subscription warnings.
        - For Level 1 (Live): Set flag to raise exception later
        - For Level 2/3 (Frozen/Delayed): Gracefully degrade to available data
        """
        if errorCode in (10089, 10091):
            # Check if Level 1 was explicitly requested
            if self._requested_market_data_type == 1:
                # Level 1 requires subscription - set flag to fail later
                error_msg = f"Level 1 (Live) market data requires subscription. {errorString}"
                logger.error(error_msg)
                self._level1_subscription_error = True
                # Store details for later exception
                self._subscription_errors.append({
                    "error_code": errorCode,
                    "error_string": errorString,
                    "contract": str(contract)
                })
            else:
                # Level 2/3: Subscription warnings are expected, data still available
                # Only log at DEBUG level to reduce noise
                logger.debug(f"Market data subscription info (Error {errorCode}): {errorString}")
        elif errorCode < 2000:  # Errors (vs warnings which are >= 2000)
            logger.error(f"IBKR Error {errorCode} for reqId {reqId}: {errorString}")
        else:
            logger.debug(f"IBKR Info {errorCode}: {errorString}")

    def _handle_subscription_error(self, error_msg: str, contract_info: str = "") -> bool:
        """
        Handle subscription/permission errors gracefully.
        Returns True if we should continue with fallback, False if we should raise.
        """
        if "subscription" in error_msg.lower() or "10091" in error_msg:
            self._subscription_errors.append({
                "contract": contract_info,
                "error": error_msg,
                "timestamp": datetime.now()
            })
            # Log level based on market data type: ERROR for Level 1, DEBUG for Level 2/3
            if self._requested_market_data_type == 1:
                logger.error(f"Subscription error (Level 1): {error_msg}. Contract: {contract_info}")
            else:
                logger.debug(f"Subscription info (Level {self._requested_market_data_type or self.market_data_type}): {error_msg}. Contract: {contract_info}")
            return self.fallback_on_subscription_error
        return False

    async def _set_market_data_type(self, market_data_type: int = None):
        """
        Change market data type dynamically.
        1=Live, 2=Frozen, 3=Delayed, 4=Delayed Frozen
        """
        try:
            mdt = market_data_type or self.market_data_type
            self._requested_market_data_type = market_data_type  # Track explicit request
            self.ib.reqMarketDataType(mdt)
            logger.info(f"Market data type set to {mdt} (requested: {market_data_type})")
        except Exception as e:
            logger.error(f"Failed to set market data type: {e}")

    async def _disconnect(self):
        """Disconnect if configured to do so."""
        if self.connect_on_request and self.ib.isConnected():
            self.ib.disconnect()
            self._connected = False
            logger.debug("Disconnected from IBKR")

    async def get_historical_prices(self, symbol: str, interval: str, start: datetime, end: datetime) -> List[PriceBar]:
        try:
            await self._ensure_connection()

            contract = Stock(symbol, 'SMART', 'USD')

            # Map interval to IBKR bar size
            bar_size = self._map_interval(interval)

            # Calculate duration string
            duration_str = self._calculate_duration(start, end)

            logger.info(f"Fetching historical prices for {symbol} ({interval}) from {start} to {end}")

            # Request data
            # whatToShow='TRADES' gives OHLCV
            bars: List[BarData] = await self.ib.reqHistoricalDataAsync(
                contract,
                endDateTime=end,
                durationStr=duration_str,
                barSizeSetting=bar_size,
                whatToShow='TRADES',
                useRTH=True,
                formatDate=1  # Flow date as string
            )

            if not bars:
                # Fallback or check errors?
                # Usually empty list implies no data
                return []

            result = []
            for b in bars:
                # IBKR bars data: date, open, high, low, close, volume...
                # Date is usually naive or localized.
                # If '1 day' bars, date is date object. If intraday, datetime.

                bar_start = b.date
                if isinstance(bar_start, date) and not isinstance(bar_start, datetime):
                    bar_start = datetime.combine(bar_start, datetime.min.time())

                # Assume end is start + interval (approx)
                # We won't be perfectly precise on 'end' without parsing interval,
                # but PriceBar needs it.
                bar_end = bar_start # Placeholder, or calculate

                result.append(PriceBar(
                    symbol=symbol,
                    start=bar_start,
                    end=bar_end, # Simplification
                    open=Decimal(str(b.open)),
                    high=Decimal(str(b.high)),
                    low=Decimal(str(b.low)),
                    close=Decimal(str(b.close)),
                    volume=int(b.volume),
                    provider="ibkr"
                ))

            logger.info(f"Retrieved {len(result)} bars for {symbol}")
            return result

        except Exception as e:
            logger.error(f"Error getting historical prices for {symbol}: {e}")
            raise ProviderError(f"IBKR error: {e}")
        finally:
            await self._disconnect()

    async def get_last_price(self, symbol: str, market_data_type: Optional[int] = None) -> PriceQuote:
        try:
            await self._ensure_connection()
            # Reset subscription errors from previous calls (e.g., from options queries)
            self._subscription_errors.clear()
            self._level1_subscription_error = False
            # Set market data type if explicitly requested (1=Live,2=Frozen,3=Delayed)
            if market_data_type is not None:
                await self._set_market_data_type(market_data_type)
            contract = Stock(symbol, 'SMART', 'USD')

            # Qualify contract to get conId etc specific to SMART
            await self.ib.qualifyContractsAsync(contract)
            logger.debug(f"Qualified contract for {symbol}: {contract}")

            # Request snapshot using helper
            tickers = await self._get_tickers_snapshot([contract])

            # Should have data
            if not tickers:
                 raise DataNotFoundError(f"No market data for {symbol}")
            ticker = tickers[0]

            # For Level 1: if any subscription error was recorded, abort with provider not available
            if self._requested_market_data_type == 1 and self._subscription_errors:
                details = self._subscription_errors[-1]
                # Reset flag for subsequent calls
                self._level1_subscription_error = False
                self._subscription_errors.clear()
                raise ProviderError(
                    "Level 1 (Live) market data requires additional subscription.",
                    code="PROVIDER_NOT_AVAILABLE",
                    details=details
                )

            # Use last price, or close, or mid...
            # If market is closed, look for 'close' or 'last'.
            # snapshot=True usually returns available data.
            logger.debug(f"Raw ticker for {symbol}: {ticker}")
            price = ticker.last if self._is_valid(ticker.last) else ticker.close
            if not self._is_valid(price):
                 price = ticker.close

            if not self._is_valid(price):
                # If Level 1 requested, abort instead of fallback
                if self._requested_market_data_type == 1:
                    details = self._subscription_errors[-1] if self._subscription_errors else {"reason": "snapshot not available"}
                    # Reset flags for subsequent calls
                    self._level1_subscription_error = False
                    self._subscription_errors.clear()
                    raise ProviderError(
                        "Level 1 (Live) market data requires additional subscription.",
                        code="PROVIDER_NOT_AVAILABLE",
                        details=details
                    )
                # Otherwise, fallback to historical data
                logger.info(f"Market data snapshot failed for {symbol}, falling back to historical data")
                end_dt = datetime.now()
                start_dt = end_dt - timedelta(days=7)
                try:
                    bars = await self.get_historical_prices(symbol, "1d", start_dt, end_dt)
                    if bars:
                        last_bar = bars[-1]
                        price = last_bar.close
                        logger.info(f"Found historical close price for {symbol}: {price}")
                    else:
                        price = 0.0
                except Exception as ex:
                    logger.warning(f"Fallback to historical data failed: {ex}")
                    price = 0.0

            quote = PriceQuote(
                symbol=symbol,
                price=Decimal(str(price)),
                currency=contract.currency,
                timestamp=ticker.time if ticker.time else datetime.now(),
                provider="ibkr",
                bid=self._to_decimal(ticker.bid),
                ask=self._to_decimal(ticker.ask),
                volume=int(ticker.volume) if self._is_valid(ticker.volume) else 0
            )
            logger.info(f"Got quote for {symbol}: {quote}")
            return quote

        except Exception as e:
            logger.error(f"Error getting last price for {symbol}: {e}")
            # If Level 1 was requested and subscription error occurred, signal provider not available
            if self._requested_market_data_type == 1:
                raise ProviderError(f"IBKR error: {e}", code="PROVIDER_NOT_AVAILABLE")
            raise ProviderError(f"IBKR error: {e}")
        finally:
            await self._disconnect()

    async def get_option_chain(
        self,
        symbol: str,
        expiry: date,
        min_strike: Optional[Decimal] = None,
        max_strike: Optional[Decimal] = None,
        right: Optional[Literal["call", "put"]] = None,
        market_data_type: Optional[int] = None
    ) -> OptionChain:
        try:
            logger.info(f"Fetching option chain for {symbol} expiry {expiry} (market_data_type={market_data_type})")
            await self._ensure_connection()

            # Set market data type if explicitly requested
            if market_data_type is not None:
                await self._set_market_data_type(market_data_type)

            # 1. Qualify underlying
            underlying = Stock(symbol, 'SMART', 'USD')
            await self.ib.qualifyContractsAsync(underlying)

            # 2. Get params
            chains = await self.ib.reqSecDefOptParamsAsync(underlying.symbol, '', underlying.secType, underlying.conId)

            if not chains:
                raise DataNotFoundError(f"No option chain found for {symbol}")

            # Filter for specific expiry
            exp_str = expiry.strftime('%Y%m%d')

            relevant_strikes = set()

            # Accumulate all strikes that exist for this expiry across exchanges
            for c in chains:
                if exp_str in c.expirations:
                    relevant_strikes.update(c.strikes)

            if not relevant_strikes:
                all_expiries = sorted(list(set(e for c in chains for e in c.expirations)))
                logger.warning(f"No options found for {symbol} at expiry {exp_str}. Available: {all_expiries[:5]}... ({len(all_expiries)} total)")
                return OptionChain(underlying_symbol=symbol, expiry=expiry, options=[], provider="ibkr")

            # Filter strikes
            sorted_strikes = sorted(list(relevant_strikes))
            if min_strike:
                 sorted_strikes = [k for k in sorted_strikes if Decimal(str(k)) >= min_strike]
            if max_strike:
                 sorted_strikes = [k for k in sorted_strikes if Decimal(str(k)) <= max_strike]

            # 3. Create Contract objects for all strikes (Call and Put)
            contracts = []
            for k in sorted_strikes:
                if right is None or right == "call":
                    contracts.append(Option(symbol, exp_str, k, 'C', 'SMART'))
                if right is None or right == "put":
                    contracts.append(Option(symbol, exp_str, k, 'P', 'SMART'))

            # 4. Request market data for them?
            # Doing snapshot for ALL might be slow.
            # Let's try to qualify them first (gets conIds)
            # Qualify in batches or one by one? Bulk is better.
            # However, if some are invalid, qualifyContractsAsync might fail or leave them without conId.
            # We must filter out those without conId before requesting data to avoid hashing errors.
            await self.ib.qualifyContractsAsync(*contracts)

            valid_contracts = [c for c in contracts if c.conId > 0]
            if len(valid_contracts) < len(contracts):
                logger.warning(f"Optimization: Filtered {len(contracts) - len(valid_contracts)} invalid option contracts")

            if not valid_contracts:
                 logger.warning("No valid option contracts found after qualification")
                 return OptionChain(underlying_symbol=symbol, expiry=expiry, options=[], provider="ibkr")

            tickers = await self._get_tickers_snapshot(valid_contracts)

            options_data = []
            for t in tickers:
                c = t.contract
                greeks = self._extract_greeks(t)
                # open_interest: populate whenever available from IBKR
                open_interest_val = int(t.openInterest) if self._is_valid(t.openInterest) else None
                options_data.append(OptionQuote(
                    symbol=c.localSymbol, # e.g. AAPL  230616C00150000
                    underlying_symbol=symbol,
                    strike=Decimal(str(c.strike)),
                    expiry=expiry,
                    type="call" if c.right == 'C' else "put",
                    # Try last, then close as fallback
                    price=self._to_decimal(t.last) or self._to_decimal(t.close) or Decimal("0.0"),
                    # Only include bid/ask if valid (not -1)
                    bid=self._to_decimal(t.bid) if t.bid != -1 else None,
                    ask=self._to_decimal(t.ask) if t.ask != -1 else None,
                    volume=int(t.volume) if self._is_valid(t.volume) else 0,
                    open_interest=open_interest_val,
                    implied_volatility=greeks["implied_volatility"],
                    delta=greeks["delta"],
                    gamma=greeks["gamma"],
                    vega=greeks["vega"],
                    theta=greeks["theta"],
                    provider="ibkr"
                ))
            logger.info(f"Retrieved {len(options_data)} options for {symbol}")
            return OptionChain(
                underlying_symbol=symbol,
                expiry=expiry,
                options=options_data,
                provider="ibkr"
            )

        except Exception as e:
            logger.error(f"Error getting option chain for {symbol}: {e}")
            raise ProviderError(f"IBKR error: {e}")
        finally:
            await self._disconnect()

    async def get_option_quote(self, symbol: str, option_id: str, market_data_type: Optional[int] = None) -> OptionQuote:
        """
        Get a specific option quote.

        Args:
            symbol: Underlying symbol
            option_id: The contract localSymbol or unique identifier
            market_data_type: Market data type (1=Live, 2=Frozen, 3=Delayed, default from config)
        """
        try:
            logger.info(f"Fetching option quote for {symbol} id {option_id} (market_data_type={market_data_type})")
            await self._ensure_connection()

            # Set market data type if explicitly requested
            if market_data_type is not None:
                await self._set_market_data_type(market_data_type)

            # We need to define contract. If we have localSymbol, we can use it.
            # But we also need exchange etc.
            contract = Contract()
            contract.symbol = symbol # Underlying? No, for Option, symbol is underlying.
            contract.secType = 'OPT'
            contract.localSymbol = option_id # Try this
            contract.exchange = 'SMART'
            contract.currency = 'USD'

            await self.ib.qualifyContractsAsync(contract)

            if not contract.conId:
                 # Try searching by parsing?
                 # Maybe option_id is more descriptive?
                 raise DataNotFoundError(f"Could not resolve option contract {option_id}")

            tickers = await self._get_tickers_snapshot([contract], skip_on_error=True)
            ticker = tickers[0] if tickers else None

            if not ticker:
                raise DataNotFoundError(f"No market data for option {option_id}")

            greeks = self._extract_greeks(ticker)

            # open_interest: populate whenever available from IBKR
            open_interest_val = int(ticker.openInterest) if self._is_valid(ticker.openInterest) else None

            return OptionQuote(
                symbol=contract.localSymbol,
                underlying_symbol=symbol,
                strike=Decimal(str(contract.strike)),
                expiry=datetime.strptime(contract.lastTradeDateOrContractMonth, '%Y%m%d').date(),
                type="call" if contract.right == 'C' else "put",
                # Try last, then close as fallback for price
                price=self._to_decimal(ticker.last) or self._to_decimal(ticker.close) or Decimal("0.0"),
                # Only include bid/ask if valid (not -1)
                bid=self._to_decimal(ticker.bid) if ticker.bid != -1 else None,
                ask=self._to_decimal(ticker.ask) if ticker.ask != -1 else None,
                volume=int(ticker.volume) if self._is_valid(ticker.volume) else 0,
                open_interest=open_interest_val,
                implied_volatility=greeks["implied_volatility"],
                delta=greeks["delta"],
                gamma=greeks["gamma"],
                vega=greeks["vega"],
                theta=greeks["theta"],
                provider="ibkr"
            )

        except Exception as e:
            logger.error(f"Error getting option quote {option_id}: {e}")
            raise ProviderError(f"IBKR error: {e}")
        finally:
            await self._disconnect()

    def _map_interval(self, interval: str) -> str:
        # Common mappings
        if interval == "1m":
            return "1 min"
        if interval == "2m":
            return "2 mins"
        if interval == "5m":
            return "5 mins"
        if interval == "15m":
            return "15 mins"
        if interval == "30m":
            return "30 mins"
        if interval == "1h":
            return "1 hour"
        if interval == "1d":
            return "1 day"
        if interval == "1w":
            return "1 week"
        return "1 day"  # Default

    def _calculate_duration(self, start: datetime, end: datetime) -> str:
        diff = end - start
        if diff.days >= 365:
            years = diff.days // 365
            return f"{years + 1} Y" # Approx
        if diff.days >= 30:
            months = diff.days // 30
            return f"{months + 1} M"
        if diff.days >= 1:
            return f"{diff.days + 1} D"

        # Less than 1 day
        seconds = diff.total_seconds()
        return f"{int(seconds) + 60} S"
    # ==================== Company Data Methods ====================

    async def get_company_profile(self, symbol: str) -> CompanyProfile:
        """
        Fetch company profile from IBKR.
        Note: IBKR provides limited company data. This includes basic contract information.
        For detailed fundamentals, use LSEG provider.
        """
        await self._ensure_connection()

        try:
            contract = Stock(symbol, "SMART", "USD")
            qualified = await self.ib.qualifyContractsAsync(contract)

            if not qualified or not qualified[0]:
                raise DataNotFoundError("Company", symbol,
                    details={"reason": "Contract could not be qualified"})

            qualified_contract = qualified[0]

            return CompanyProfile(
                symbol=symbol,
                name=qualified_contract.longName or symbol,
                exchange=qualified_contract.exchange or "UNKNOWN",
                currency=qualified_contract.currency or "USD",
                provider="ibkr"
            )

        except DataNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error fetching company profile for {symbol} from IBKR: {e}")
            raise ProviderError(f"IBKR company lookup failed for {symbol}",
                details={"error": str(e)})

    async def search_companies(self, query: str) -> List[CompanySummary]:
        """
        Search for companies in IBKR.
        Note: IBKR does not provide a search API. This attempts to qualify the query as a symbol.
        For full company search, use LSEG provider.
        """
        await self._ensure_connection()

        try:
            # Try to treat query as a symbol
            contract = Stock(query.upper(), "SMART", "USD")
            qualified = await self.ib.qualifyContractsAsync(contract)

            if not qualified or not qualified[0]:
                return []

            qualified_contract = qualified[0]

            return [
                CompanySummary(
                    symbol=query.upper(),
                    name=qualified_contract.longName or query.upper(),
                    exchange=qualified_contract.exchange or "UNKNOWN",
                    provider="ibkr"
                )
            ]

        except Exception as e:
            logger.warning(f"Error searching companies in IBKR for '{query}': {e}")
            return []

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
        """Get news articles for a company from IBKR."""
        await self._ensure_connection()

        try:
            # 1. Create and qualify contract
            contract = Stock(symbol, 'SMART', 'USD')
            qualified = await self.ib.qualifyContractsAsync(contract)
            if not qualified:
                raise DataNotFoundError("Contract", symbol)

            contract = qualified[0]

            # 2. Request historical news from IBKR
            news_items = await self.ib.reqHistoricalNewsAsync(
                conId=contract.conId,
                providerCodes='',  # All news providers
                startDateTime=f"{from_date.isoformat()} 00:00:00",
                endDateTime=f"{to_date.isoformat()} 23:59:59",
                totalResults=limit + offset
            )

            if not news_items:
                return []

            # 3. Apply offset and limit
            news_items = news_items[offset:offset + limit]

            # 4. Parse news items
            articles = []
            for item in news_items:
                article_id = f"ibkr:{item.articleId}"

                # Parse timestamp
                published_at = datetime.fromtimestamp(item.time, tz=datetime.now().astimezone().tzinfo)

                # 5. Detect category from headline (IBKR doesn't provide explicit categories)
                title_lower = item.headline.lower()
                article_category = None
                if 'earnings' in title_lower or 'profit' in title_lower or 'revenue' in title_lower:
                    article_category = 'earnings'
                elif 'merger' in title_lower or 'acquisition' in title_lower or 'buyout' in title_lower:
                    article_category = 'merger'
                elif 'product' in title_lower or 'launch' in title_lower or 'release' in title_lower:
                    article_category = 'product'
                elif 'lawsuit' in title_lower or 'regulation' in title_lower or 'sec' in title_lower:
                    article_category = 'legal'

                # 6. Apply category filter
                if category and article_category != category:
                    continue

                # 7. Create article object
                articles.append(NewsArticle(
                    article_id=article_id,
                    title=item.headline,
                    summary=item.headline,  # IBKR doesn't provide separate summary
                    published_at=published_at,
                    source=item.providerCode,
                    url='',  # IBKR doesn't provide direct URLs
                    full_text=None,  # Not available in historical news
                    category=article_category
                ))

            return articles

        except DataNotFoundError:
            raise
        except Exception as e:
            logger.error(f"IBKR news error for {symbol}: {e}")
            raise ProviderError(f"Failed to fetch news from IBKR: {str(e)}")
            return []