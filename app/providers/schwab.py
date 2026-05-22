import asyncio
import logging
import os
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from app.config import settings
from app.models.price import PriceBar, PriceQuote
from app.providers.base import BasePriceProvider
from app.utils.errors import (
    DataNotFoundError,
    DataValidationError,
    ProviderConnectionError,
    ProviderError,
    ProviderTimeoutError,
)

try:
    from schwab.auth import easy_client
except ImportError:  # pragma: no cover
    easy_client = None


logger = logging.getLogger(__name__)


class SchwabProvider(BasePriceProvider):
    _INTERVAL_METHODS: Dict[str, str] = {
        "1m": "get_price_history_every_minute",
        "5m": "get_price_history_every_five_minutes",
        "10m": "get_price_history_every_ten_minutes",
        "15m": "get_price_history_every_fifteen_minutes",
        "30m": "get_price_history_every_thirty_minutes",
        "1d": "get_price_history_every_day",
        "1w": "get_price_history_every_week",
    }

    def __init__(self) -> None:
        self._client = None
        self._client_lock = asyncio.Lock()
        self._request_times: deque[float] = deque(maxlen=max(1, settings.SCHWAB_RATE_LIMIT_PER_SEC))

    def _ensure_configured(self) -> None:
        if not settings.SCHWAB_API_KEY:
            raise ProviderConnectionError(
                "Schwab provider is not configured. Set SCHWAB_API_KEY to enable it.",
                details={"setting": "SCHWAB_API_KEY"},
            )

    async def _get_client(self):
        self._ensure_configured()
        if self._client is not None:
            return self._client

        async with self._client_lock:
            if self._client is not None:
                return self._client

            if not os.path.exists(settings.SCHWAB_TOKEN_PATH):
                raise ProviderConnectionError(
                    "Schwab token file not found.",
                    details={"token_path": settings.SCHWAB_TOKEN_PATH},
                )

            if easy_client is None:
                raise ProviderConnectionError(
                    "schwab-py is not installed. Install dependencies and retry.",
                    details={"dependency": "schwab-py"},
                )

            def _create_client():
                return easy_client(
                    api_key=settings.SCHWAB_API_KEY,
                    app_secret=settings.SCHWAB_APP_SECRET,
                    callback_url=settings.SCHWAB_CALLBACK_URL,
                    token_path=settings.SCHWAB_TOKEN_PATH,
                    asyncio=settings.SCHWAB_ASYNCIO,
                )

            try:
                self._client = await asyncio.to_thread(_create_client)
            except FileNotFoundError as exc:
                raise ProviderConnectionError(
                    "Schwab token file not found.",
                    details={"token_path": settings.SCHWAB_TOKEN_PATH, "error": str(exc)},
                ) from exc
            except Exception as exc:
                raise ProviderConnectionError(
                    "Failed to authenticate with Schwab. Re-generate token with schwab-generate-token.py.",
                    details={"error": str(exc), "token_path": settings.SCHWAB_TOKEN_PATH},
                ) from exc

        return self._client

    def _check_rate_limit(self) -> None:
        limit = settings.SCHWAB_RATE_LIMIT_PER_SEC
        if limit <= 0:
            return

        now = time.time()
        while self._request_times and now - self._request_times[0] > 1.0:
            self._request_times.popleft()

        if len(self._request_times) >= limit:
            raise ProviderTimeoutError(
                "schwab",
                details={
                    "reason": "rate limit exceeded",
                    "rate_limit_per_sec": limit,
                },
            )

        self._request_times.append(now)

    def _period_to_start(self, period: str) -> datetime:
        now = datetime.now(timezone.utc)
        mapping = {
            "1d": timedelta(days=1),
            "5d": timedelta(days=5),
            "1m": timedelta(days=30),
            "3m": timedelta(days=90),
            "6m": timedelta(days=180),
            "1y": timedelta(days=365),
            "2y": timedelta(days=730),
            "5y": timedelta(days=1825),
            "10y": timedelta(days=3650),
        }
        delta = mapping.get(period)
        if delta is None:
            raise DataValidationError(
                f"Unsupported period '{period}'.",
                details={"valid_periods": sorted(mapping.keys())},
            )
        return now - delta

    def _parse_ohlcv(self, data: Dict[str, Any], symbol: str) -> List[PriceBar]:
        candles = data.get("candles", []) if isinstance(data, dict) else []
        if not isinstance(candles, list):
            raise DataValidationError(
                "Invalid Schwab candles payload.",
                details={"symbol": symbol},
            )

        bars: List[PriceBar] = []
        for candle in candles:
            if not isinstance(candle, dict):
                continue

            try:
                ts_ms = candle["datetime"]
                ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
                bars.append(
                    PriceBar(
                        symbol=symbol,
                        start=ts,
                        end=ts,
                        open=Decimal(str(candle["open"])),
                        high=Decimal(str(candle["high"])),
                        low=Decimal(str(candle["low"])),
                        close=Decimal(str(candle["close"])),
                        volume=int(candle.get("volume", 0)),
                        provider="schwab",
                    )
                )
            except KeyError as exc:
                raise DataValidationError(
                    "Malformed candle in Schwab response.",
                    details={"symbol": symbol, "missing_field": str(exc)},
                ) from exc

        return bars

    def _parse_quote(self, symbol: str, data: Dict[str, Any]) -> PriceQuote:
        entry = data.get(symbol) or data.get(symbol.upper())
        if not entry:
            raise DataNotFoundError("Symbol", symbol)

        quote = entry.get("quote", {}) if isinstance(entry, dict) else {}
        last_price = quote.get("lastPrice")
        if last_price is None:
            raise DataNotFoundError("Quote", symbol)

        return PriceQuote(
            symbol=symbol,
            price=Decimal(str(last_price)),
            currency="USD",
            timestamp=datetime.now(timezone.utc),
            provider="schwab",
            bid=Decimal(str(quote["bidPrice"])) if quote.get("bidPrice") is not None else None,
            ask=Decimal(str(quote["askPrice"])) if quote.get("askPrice") is not None else None,
            volume=int(quote["totalVolume"]) if quote.get("totalVolume") is not None else None,
        )

    async def get_historical_prices(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
        sec_type: str = "stock",
        period: Optional[str] = None,
    ) -> List[PriceBar]:
        del sec_type
        self._check_rate_limit()
        client = await self._get_client()

        method_name = self._INTERVAL_METHODS.get(interval)
        if method_name is None:
            raise DataValidationError(
                f"Unsupported interval '{interval}'.",
                details={"valid_intervals": sorted(self._INTERVAL_METHODS.keys())},
            )

        method = getattr(client, method_name, None)
        if method is None:
            raise ProviderConnectionError(
                "Schwab client does not expose required history method.",
                details={"method": method_name},
            )

        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        if period:
            start = self._period_to_start(period)
            end = datetime.now(timezone.utc)

        response = await method(
            symbol=symbol,
            start_datetime=start,
            end_datetime=end,
            need_extended_hours_data=True,
        )

        if response.status_code == 429:
            raise ProviderTimeoutError("schwab", details={"status_code": 429})
        if response.status_code != 200:
            raise ProviderError(
                f"Schwab historical price request failed for {symbol}.",
                details={"status_code": response.status_code, "interval": interval},
            )

        bars = self._parse_ohlcv(response.json(), symbol)
        if not bars:
            raise DataNotFoundError("Historical data", symbol)

        return bars

    async def get_last_price(
        self,
        symbol: str,
        market_data_type: Optional[int] = None,
        sec_type: str = "stock",
    ) -> PriceQuote:
        del market_data_type, sec_type
        self._check_rate_limit()
        client = await self._get_client()

        response = await client.get_quotes([symbol])
        if response.status_code == 429:
            raise ProviderTimeoutError("schwab", details={"status_code": 429})
        if response.status_code != 200:
            raise ProviderError(
                f"Schwab quote request failed for {symbol}.",
                details={"status_code": response.status_code},
            )

        return self._parse_quote(symbol, response.json())

    async def close(self) -> None:
        if self._client is None:
            return

        close_method = getattr(self._client, "close", None)
        if close_method is None:
            self._client = None
            return

        maybe_coro = close_method()
        if asyncio.iscoroutine(maybe_coro):
            await maybe_coro

        self._client = None
