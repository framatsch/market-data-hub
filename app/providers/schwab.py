"""Schwab provider for US equity price data (quotes + historical OHLCV).

Authentication model:
  - Uses schwab-py's easy_client() with an OAuth2 token file (default: ./schwab_token.json).
  - Token file must be generated once via schwab-generate-token.py and rotated every 7 days.
  - Set SCHWAB_ASYNCIO=True (default) to receive an async httpx client from schwab-py.
    When SCHWAB_ASYNCIO=False, easy_client() returns a sync client — used in non-async contexts.
  - asyncio.to_thread is used for the synchronous easy_client() factory call (it only reads
    the token file and returns a client object; it does not perform any async network I/O).
"""

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from app.config import settings
from app.models.price import PriceBar, PriceQuote
from app.providers.base import BasePriceProvider
from app.utils.secrets import unwrap_secret
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

_RATE_WINDOW_SECS = 1.0
_HTTP_OK = 200
_HTTP_RATE_LIMITED = 429
_HTTP_UNAUTHORIZED = 401
_HTTP_FORBIDDEN = 403


class SchwabProvider(BasePriceProvider):
    """Schwab Individual Trader API provider.

    Supports:
    - get_last_price: delayed quote via get_quotes()
    - get_historical_prices: OHLCV bars (1m–1w) via price history endpoints

    Rate limiting: sliding-window deque, SCHWAB_RATE_LIMIT_PER_SEC (default 5).
    Timeout: SCHWAB_TIMEOUT_SECONDS applied via asyncio.wait_for (default 30s).
    Token rotation: every 7 days; 401/403 clears the cached client automatically.
    """

    _INTERVAL_METHODS: dict[str, str] = {
        "1m": "get_price_history_every_minute",
        "5m": "get_price_history_every_five_minutes",
        "10m": "get_price_history_every_ten_minutes",
        "15m": "get_price_history_every_fifteen_minutes",
        "30m": "get_price_history_every_thirty_minutes",
        "1d": "get_price_history_every_day",
        "1w": "get_price_history_every_week",
    }

    def __init__(self) -> None:
        self._client: Any = None
        # Locks are created lazily inside the running event loop (Python 3.12+ safe).
        self._client_lock: Optional[asyncio.Lock] = None
        self._rate_limit_lock: Optional[asyncio.Lock] = None
        self._request_times: deque[float] = deque()  # no maxlen — managed manually

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_client_lock(self) -> asyncio.Lock:
        if self._client_lock is None:
            self._client_lock = asyncio.Lock()
        return self._client_lock

    def _get_rate_limit_lock(self) -> asyncio.Lock:
        if self._rate_limit_lock is None:
            self._rate_limit_lock = asyncio.Lock()
        return self._rate_limit_lock

    def _ensure_configured(self) -> None:
        key_value = unwrap_secret(settings.SCHWAB_API_KEY)
        if not key_value:
            raise ProviderConnectionError(
                "Schwab provider is not configured. Set SCHWAB_API_KEY to enable it.",
                details={"setting": "SCHWAB_API_KEY"},
            )

    async def _get_client(self) -> Any:
        self._ensure_configured()
        if self._client is not None:
            return self._client

        async with self._get_client_lock():
            if self._client is not None:
                return self._client

            if not Path(settings.SCHWAB_TOKEN_PATH).exists():
                raise ProviderConnectionError(
                    "Schwab token file not found. Re-run schwab-generate-token.py.",
                    details={"hint": "Set SCHWAB_TOKEN_PATH to the token file location."},
                )

            if easy_client is None:
                raise ProviderConnectionError(
                    "schwab-py is not installed. Install dependencies and retry.",
                    details={"dependency": "schwab-py"},
                )

            key_value = unwrap_secret(settings.SCHWAB_API_KEY)
            secret_value = unwrap_secret(settings.SCHWAB_APP_SECRET)

            def _create_client() -> Any:
                # easy_client() is a synchronous factory: reads the token file and
                # returns an async httpx client when asyncio=True. It does NOT perform
                # network I/O during construction, so asyncio.to_thread is safe here.
                return easy_client(
                    api_key=key_value,
                    app_secret=secret_value,
                    callback_url=settings.SCHWAB_CALLBACK_URL,
                    token_path=settings.SCHWAB_TOKEN_PATH,
                    asyncio=settings.SCHWAB_ASYNCIO,
                )

            try:
                self._client = await asyncio.to_thread(_create_client)
            except FileNotFoundError:
                raise ProviderConnectionError(
                    "Schwab token file not found. Re-run schwab-generate-token.py.",
                    details={"hint": "Set SCHWAB_TOKEN_PATH to the token file location."},
                )
            except Exception as exc:
                raise ProviderConnectionError(
                    "Failed to authenticate with Schwab. Re-generate token with schwab-generate-token.py.",
                    details={"hint": f"Auth error: {type(exc).__name__}"},
                ) from exc

        return self._client

    async def _check_rate_limit(self) -> None:
        """Sliding-window rate limiter — async-safe via asyncio.Lock."""
        limit = settings.SCHWAB_RATE_LIMIT_PER_SEC
        if limit <= 0:
            return

        async with self._get_rate_limit_lock():
            now = time.time()
            while self._request_times and now - self._request_times[0] > _RATE_WINDOW_SECS:
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

    def _parse_ohlcv(self, data: dict[str, Any], symbol: str) -> list[PriceBar]:
        candles = data.get("candles", []) if isinstance(data, dict) else []
        if not isinstance(candles, list):
            raise DataValidationError(
                "Invalid Schwab candles payload.",
                details={"symbol": symbol},
            )

        bars: list[PriceBar] = []
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
            except (KeyError, ValueError, TypeError) as exc:
                raise DataValidationError(
                    "Malformed candle in Schwab response.",
                    details={"symbol": symbol, "missing_field": str(exc)},
                ) from exc

        return bars

    def _parse_quote(self, symbol: str, data: dict[str, Any]) -> PriceQuote:
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

    def _handle_error_status(self, status_code: int, symbol: str, context: str) -> None:
        """Map Schwab HTTP error codes to appropriate AppError types."""
        if status_code == _HTTP_RATE_LIMITED:
            raise ProviderTimeoutError("schwab", details={"status_code": status_code})
        if status_code in (_HTTP_UNAUTHORIZED, _HTTP_FORBIDDEN):
            # Clear cached client so the next call re-authenticates
            self._client = None
            raise ProviderConnectionError(
                "Schwab token has expired or is invalid. Re-run schwab-generate-token.py.",
                details={"hint": "Token rotation required every 7 days."},
            )
        raise ProviderError(
            f"Schwab {context} request failed for {symbol}.",
            details={"status_code": status_code},
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def get_historical_prices(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
        sec_type: str = "stock",  # noqa: ARG002 — Schwab infers security type automatically
    ) -> list[PriceBar]:
        await self._check_rate_limit()
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

        try:
            response = await asyncio.wait_for(
                method(
                    symbol=symbol,
                    start_datetime=start,
                    end_datetime=end,
                    need_extended_hours_data=True,
                ),
                timeout=settings.SCHWAB_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            raise ProviderTimeoutError(
                "schwab",
                details={"reason": "request timeout", "timeout_seconds": settings.SCHWAB_TIMEOUT_SECONDS},
            )

        if response.status_code != _HTTP_OK:
            self._handle_error_status(response.status_code, symbol, "historical price")

        bars = self._parse_ohlcv(response.json(), symbol)
        if not bars:
            raise DataNotFoundError("Historical data", symbol)

        return bars

    async def get_last_price(
        self,
        symbol: str,
        market_data_type: Optional[int] = None,  # noqa: ARG002 — Schwab returns delayed quotes only
        sec_type: str = "stock",  # noqa: ARG002 — Schwab infers security type automatically
    ) -> PriceQuote:
        await self._check_rate_limit()
        client = await self._get_client()

        try:
            response = await asyncio.wait_for(
                client.get_quotes([symbol]),
                timeout=settings.SCHWAB_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            raise ProviderTimeoutError(
                "schwab",
                details={"reason": "request timeout", "timeout_seconds": settings.SCHWAB_TIMEOUT_SECONDS},
            )

        if response.status_code != _HTTP_OK:
            self._handle_error_status(response.status_code, symbol, "quote")

        return self._parse_quote(symbol, response.json())

    async def close(self) -> None:
        """Gracefully close the underlying schwab-py HTTP session."""
        async with self._get_client_lock():
            try:
                if self._client is None:
                    return
                close_method = getattr(self._client, "close", None)
                if close_method is None:
                    return
                maybe_coro = close_method()
                if asyncio.iscoroutine(maybe_coro):
                    await maybe_coro
            finally:
                self._client = None
