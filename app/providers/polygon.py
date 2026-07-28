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
import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

import httpx

from app.config import settings
from app.models.common import MarketStatus
from app.models.company import CompanyProfile, CompanySummary
from app.models.options import OptionChain, OptionQuote
from app.models.price import PriceBar, PriceQuote
from app.providers.base import (
    BaseCompanyProvider,
    BaseOptionsProvider,
    BasePriceProvider,
)
from app.providers.credentials import get_provider_credential_sync
from app.utils.errors import DataNotFoundError, ProviderError

logger = logging.getLogger(__name__)

class PolygonProvider(BasePriceProvider, BaseOptionsProvider, BaseCompanyProvider):
    """Polygon.io provider for US Stocks and Options."""

    def __init__(self) -> None:
        self.api_key: str | None = None
        self.base_url = settings.POLYGON_BASE_URL
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=10.0)

    async def _get_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        self.api_key = await asyncio.to_thread(get_provider_credential_sync, "polygon", "api_key")
        return self.api_key

    async def close(self) -> None:
        await self._client.aclose()

    async def test_connection(self) -> dict[str, Any]:
        """Validate Polygon API key with a lightweight previous-close request."""
        try:
            api_key = await self._get_api_key()
            response = await self._client.get(
                "/v2/aggs/ticker/AAPL/prev",
                params={"apiKey": api_key, "adjusted": "true"},
            )

            if response.status_code == 200:
                return {
                    "status_code": 200,
                    "success": True,
                    "message": "Polygon API key valid",
                    "details": {"endpoint": "/v2/aggs/ticker/AAPL/prev"},
                }
            if response.status_code in (401, 403):
                return {
                    "status_code": 401,
                    "success": False,
                    "message": "Invalid Polygon API key",
                    "details": {"status_code": response.status_code, "response": response.text[:500]},
                }

            return {
                "status_code": 503,
                "success": False,
                "message": "Polygon service unavailable",
                "details": {"status_code": response.status_code, "response": response.text[:500]},
            }
        except httpx.TimeoutException as exc:
            return {
                "status_code": 503,
                "success": False,
                "message": "Polygon service unavailable",
                "details": {"error": str(exc), "reason": "timeout"},
            }
        except Exception as exc:
            return {
                "status_code": 503,
                "success": False,
                "message": "Polygon service unavailable",
                "details": {"error": str(exc)},
            }

    def _format_ticker(self, symbol: str, sec_type: str) -> str:
        """Format symbol for Polygon API."""
        symbol = symbol.upper()
        if sec_type == "option":
            # Polygon options use O: prefix
            if not symbol.startswith("O:"):
                return f"O:{symbol}"
        return symbol

    async def get_last_price(self, symbol: str, market_data_type: int | None = None, sec_type: str = "stock") -> PriceQuote:
        ticker = self._format_ticker(symbol, sec_type)
        api_key = await self._get_api_key()
        
        url = f"/v2/last/nbbo/{ticker}"
        params = {"apiKey": api_key}
        
        try:
            resp = await self._client.get(url, params=params)
            
            # Handle 403 Forbidden - likely Free Tier trying to access real-time NBBO
            if resp.status_code == 403:
                logger.info(f"Polygon NBBO restricted (403) for {ticker}. Attempting fallback to Previous Close...")
                return await self._get_last_price_fallback(symbol, ticker)

            if resp.status_code == 404:
                raise DataNotFoundError("Ticker", ticker)
                
            resp.raise_for_status()
            
            data = resp.json().get("results", {})
            if not data:
                raise DataNotFoundError("PriceData", ticker)

            price = Decimal(str(data.get("p", 0) or data.get("P", 0)))
            bid = Decimal(str(data.get("b", 0) or data.get("B", 0)))
            ask = Decimal(str(data.get("a", 0) or data.get("A", 0)))
            
            timestamp_ns = data.get("t", 0) or data.get("T", 0)
            timestamp = datetime.fromtimestamp(timestamp_ns / 1e9) if timestamp_ns else datetime.now()

            return PriceQuote(
                symbol=symbol.upper(),
                price=price,
                currency="USD",
                bid=bid,
                ask=ask,
                timestamp=timestamp,
                provider="polygon"
            )
        except DataNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Polygon API error: {e}", exc_info=True)
            raise ProviderError(f"Polygon API error: {e!s}")

    async def _get_last_price_fallback(self, symbol: str, ticker: str) -> PriceQuote:
        """Fallback for free tier users using the Previous Close endpoint."""
        api_key = await self._get_api_key()
        url = f"/v2/aggs/ticker/{ticker}/prev"
        params = {"apiKey": api_key, "adjusted": "true"}
        
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            
            results = resp.json().get("results", [])
            if not results:
                raise DataNotFoundError("FallbackPriceData", ticker)
            
            data = results[0]
            return PriceQuote(
                symbol=symbol.upper(),
                price=Decimal(str(data["c"])),
                currency="USD",
                bid=None,
                ask=None,
                timestamp=datetime.fromtimestamp(data["t"] / 1000),
                provider="polygon (delayed/prev)"
            )
        except DataNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Polygon fallback failed: {e}")
            raise ProviderError(f"Polygon fallback failed: {e!s}")

    async def get_historical_prices(
        self, 
        symbol: str, 
        interval: str, 
        start: datetime, 
        end: datetime, 
        extended_hours: bool = False,
        sec_type: str = "STK"
    ) -> list[PriceBar]:
        ticker = self._format_ticker(symbol, sec_type)
        api_key = await self._get_api_key()
        
        # Map MDH interval to Polygon
        multiplier = 1
        timespan = "day"
        
        if interval == "1m":
            timespan = "minute"
        elif interval == "5m":
            multiplier = 5
            timespan = "minute"
        elif interval == "1h":
            timespan = "hour"
        elif interval == "1d":
            timespan = "day"
        else:
            raise ProviderError(
                f"Unsupported interval '{interval}' for Polygon provider.",
                details={"supported_intervals": ["1m", "5m", "1h", "1d"]}
            )

        from_str = start.strftime("%Y-%m-%d")
        to_str = end.strftime("%Y-%m-%d")
        
        url = f"/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from_str}/{to_str}"
        params = {
            "apiKey": api_key,
            "adjusted": "true",
            "sort": "asc"
        }
        
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            
            results = resp.json().get("results", [])
            bars = []
            for r in results:
                bar_start = datetime.fromtimestamp(r["t"] / 1000, tz=UTC)
                # For daily bars, 'end' is roughly same day, but MDH expects a range
                # We'll set end to start + interval logic
                bars.append(PriceBar(
                    symbol=symbol.upper(),
                    start=bar_start,
                    end=bar_start, # Simplified for now
                    open=Decimal(str(r["o"])),
                    high=Decimal(str(r["h"])),
                    low=Decimal(str(r["l"])),
                    close=Decimal(str(r["c"])),
                    volume=int(r["v"]),
                    provider="polygon"
                ))
            if not extended_hours and interval in ["1m", "5m", "1h"]:
                bars = self._filter_rth(bars)
                
            return bars
        except Exception as e:
            logger.error(f"Polygon Aggs error: {e}")
            raise ProviderError(f"Polygon Aggs error: {e!s}")

    def _filter_rth(self, bars: list[PriceBar]) -> list[PriceBar]:
        """Filter out extended trading hours. Keeps only 09:30-16:00 ET."""
        from datetime import time
        from zoneinfo import ZoneInfo
        
        filtered = []
        tz = ZoneInfo("America/New_York")
        market_open = time(9, 30)
        market_close = time(16, 0)
        
        for bar in bars:
            # Convert naive UTC or aware UTC to NY time
            if bar.start.tzinfo is None:
                ny_time = bar.start.replace(tzinfo=UTC).astimezone(tz)
            else:
                ny_time = bar.start.astimezone(tz)
                
            # Filter Monday (0) to Friday (4) and within trading hours
            if ny_time.weekday() < 5 and market_open <= ny_time.time() < market_close:
                filtered.append(bar)
                
        return filtered

    async def get_option_chain(
        self,
        symbol: str,
        expiry: date,
        min_strike: Decimal | None = None,
        max_strike: Decimal | None = None,
        right: Literal['call', 'put'] | None = None,
        market_data_type: int | None = None,
        **kwargs: Any
    ) -> OptionChain:
        """Fetch option chain using Polygon Snapshots."""
        api_key = await self._get_api_key()
        url = f"/v3/snapshot/options/{symbol.upper()}"
        params: dict[str, str | int] = {
            "apiKey": api_key,
            "expiration_date": expiry.isoformat(),
            "limit": 250
        }
        
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            
            results = resp.json().get("results", [])
            quotes = []
            for r in results:
                details = r.get("details", {})
                greeks = r.get("greeks", {})
                
                quotes.append(OptionQuote(
                    symbol=r["ticker"],
                    underlying_symbol=symbol.upper(),
                    strike=Decimal(str(details.get("strike_price", 0))),
                    expiry=date.fromisoformat(details.get("expiration_date")),
                    type="call" if details.get("contract_type") == "call" else "put",
                    price=Decimal(str(r.get("day", {}).get("last_price", 0) or 0)),
                    bid=Decimal(str(r.get("last_quote", {}).get("bid", 0) or 0)),
                    ask=Decimal(str(r.get("last_quote", {}).get("ask", 0) or 0)),
                    volume=int(r.get("day", {}).get("volume", 0) or 0),
                    open_interest=int(r.get("open_interest", 0) or 0),
                    delta=float(greeks.get("delta", 0) or 0),
                    gamma=float(greeks.get("gamma", 0) or 0),
                    theta=float(greeks.get("theta", 0) or 0),
                    vega=float(greeks.get("vega", 0) or 0),
                    implied_volatility=float(r.get("implied_volatility", 0) or 0),
                    provider="polygon"
                ))
            
            return OptionChain(
                underlying_symbol=symbol.upper(),
                expiry=expiry,
                options=quotes,
                provider="polygon"
            )
        except Exception as e:
            logger.error(f"Polygon Snapshot error: {e}")
            raise ProviderError(f"Polygon Snapshot error: {e!s}")

    async def get_option_quote(self, symbol: str, option_id: str, market_data_type: int | None = None) -> OptionQuote:
        """Fetch quote for a specific option contract."""
        api_key = await self._get_api_key()
        url = f"/v3/snapshot/options/{symbol.upper()}/{self._format_ticker(option_id, 'option')}"
        params = {"apiKey": api_key}
        
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json().get("results", {})
            
            details = data.get("details", {})
            greeks = data.get("greeks", {})
            day = data.get("day", {})
            last_quote = data.get("last_quote", {})
            
            return OptionQuote(
                symbol=option_id.upper(),
                underlying_symbol=symbol.upper(),
                strike=Decimal(str(details.get("strike_price", 0))),
                expiry=date.fromisoformat(details.get("expiration_date")),
                type="call" if details.get("contract_type") == "call" else "put",
                price=Decimal(str(day.get("last_price", 0) or 0)),
                bid=Decimal(str(last_quote.get("bid", 0) or 0)),
                ask=Decimal(str(last_quote.get("ask", 0) or 0)),
                volume=int(day.get("volume", 0) or 0),
                open_interest=int(data.get("open_interest", 0) or 0),
                delta=float(greeks.get("delta", 0) or 0),
                gamma=float(greeks.get("gamma", 0) or 0),
                theta=float(greeks.get("theta", 0) or 0),
                vega=float(greeks.get("vega", 0) or 0),
                implied_volatility=float(data.get("implied_volatility", 0) or 0),
                provider="polygon"
            )
        except Exception as e:
            logger.error(f"Polygon Snapshot error for specific quote: {e}")
            raise ProviderError(f"Polygon Snapshot error: {e!s}")

    async def get_market_status(self) -> MarketStatus:
        """Fetch current market status from Polygon."""
        api_key = await self._get_api_key()
        url = "/v1/marketstatus/now"
        params = {"apiKey": api_key}
        
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            
            return MarketStatus(
                market=data.get("market", "unknown"),
                exchanges=data.get("exchanges"),
                server_time=datetime.fromisoformat(data.get("serverTime").replace("Z", "+00:00")),
                provider="polygon"
            )
        except Exception as e:
            logger.error(f"Polygon Market Status error: {e}")
            raise ProviderError(f"Polygon Market Status error: {e}")

    async def get_company_profile(self, symbol: str) -> CompanyProfile:
        """Fetch company profile using Polygon Ticker Details v3."""
        api_key = await self._get_api_key()
        url = f"/v3/reference/tickers/{symbol.upper()}"
        params = {"apiKey": api_key}
        
        try:
            resp = await self._client.get(url, params=params)
            if resp.status_code == 404:
                raise DataNotFoundError("Company", symbol)
            resp.raise_for_status()
            
            results = resp.json().get("results", {})
            
            return CompanyProfile(
                symbol=results.get("ticker"),
                name=results.get("name"),
                description=results.get("description"),
                exchange=results.get("primary_exchange", "UNKNOWN"),
                currency=results.get("currency_name", "USD").upper(),
                website=results.get("homepage_url"),
                sector=results.get("sic_description"),
                industry=results.get("sic_description"),
                employees=results.get("total_employees"),
                provider="polygon"
            )
        except DataNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Polygon Ticker Details error: {e}")
            raise ProviderError(f"Polygon Ticker Details error: {e}")

    async def search_companies(self, query: str) -> list[CompanySummary]:
        """Search for companies using Polygon Tickers v3."""
        api_key = await self._get_api_key()
        url = "/v3/reference/tickers"
        params: dict[str, str | int] = {
            "apiKey": api_key,
            "search": query,
            "active": "true",
            "limit": 10
        }
        
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            
            results = resp.json().get("results", [])
            summaries = []
            for r in results:
                summaries.append(CompanySummary(
                    symbol=r.get("ticker"),
                    name=r.get("name"),
                    exchange=r.get("primary_exchange", "UNKNOWN"),
                    provider="polygon"
                ))
            return summaries
        except Exception as e:
            logger.error(f"Polygon Ticker Search error: {e}")
            raise ProviderError(f"Polygon Ticker Search error: {e}")
