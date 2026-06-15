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
import os
import re
import tempfile
import time
from collections import deque
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Optional, cast

from app.config import settings
from app.models.options import OptionChain, OptionQuote
from app.models.price import PriceBar, PriceQuote
from app.providers.base import BaseOptionsProvider, BasePriceProvider
from app.utils.errors import (
    AppError,
    DataNotFoundError,
    DataValidationError,
    ProviderConnectionError,
    ProviderError,
    ProviderTimeoutError,
)
from app.utils.webhooks import validate_webhook_url

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
_OCC_OPTION_SYMBOL_RE = re.compile(r"^([A-Z]+)\s+(\d{6})([CP])(\d{8})$")


class SchwabProvider(BasePriceProvider, BaseOptionsProvider):
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
        self._paused = False
        self._temp_token_path: str | None = None
        self._client_lock = asyncio.Lock()
        self._rate_limit_lock = asyncio.Lock()
        self._request_times: deque[float] = deque()  # no maxlen — managed manually
        self.timeout_seconds = settings.SCHWAB_TIMEOUT_SECONDS
        self.rate_limit_per_sec = settings.SCHWAB_RATE_LIMIT_PER_SEC

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_client_lock(self) -> asyncio.Lock:
        return self._client_lock

    def _get_rate_limit_lock(self) -> asyncio.Lock:
        return self._rate_limit_lock

    def configure(self, config: Any) -> None:
        super().configure(config)
        self.timeout_seconds = config.timeout_seconds
        self.rate_limit_per_sec = config.rate_limit_per_sec

    @property
    def is_paused(self) -> bool:
        return self._paused

    def _cleanup_temp_token_file(self) -> None:
        if self._temp_token_path is None:
            return
        try:
            Path(self._temp_token_path).unlink(missing_ok=True)
        except OSError:
            logger.warning("Failed to remove Schwab temp token file", exc_info=True)
        finally:
            self._temp_token_path = None

    async def _load_repository_credential(self, credential_name: str) -> str | None:
        try:
            from app.admin.runtime import get_key_repository

            return await get_key_repository().get("schwab", credential_name)
        except RuntimeError:
            return None

    async def _get_credentials(self) -> tuple[str, str]:
        key_value = await self._load_repository_credential("api_key")
        secret_value = await self._load_repository_credential("app_secret")
        if not key_value:
            raise ProviderConnectionError(
                "Schwab provider is not configured. Set schwab.api_key in admin credentials.",
                details={"credential": "schwab.api_key"},
            )
        if not secret_value:
            raise ProviderConnectionError(
                "Schwab provider is not configured. Set schwab.app_secret in admin credentials.",
                details={"credential": "schwab.app_secret"},
            )
        return key_value, secret_value

    async def _resolve_token_path(self) -> str:
        token_json = await self._load_repository_credential("token_json")
        if token_json is not None:
            try:
                import json
                token_data = json.loads(token_json)
                token_item = token_data.get("token", token_data)
                creation_ts = token_item.get("creation_timestamp")
                if creation_ts:
                    creation = datetime.fromtimestamp(creation_ts, tz=timezone.utc)
                    days_remaining = 7 - (datetime.now(timezone.utc) - creation).days
                    if days_remaining <= 3:
                        logger.warning(
                            "Schwab token is near expiry",
                            extra={"event": "schwab_token_expiry", "days_remaining": max(0, days_remaining)}
                        )
            except Exception:
                pass

            self._cleanup_temp_token_file()
            fd, path = tempfile.mkstemp(suffix=".json")
            os.chmod(path, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
                temp_file.write(token_json)
            self._temp_token_path = path
            return path

        raise ProviderConnectionError(
            "Schwab token not found. Re-authorize Schwab through the admin UI.",
            details={"hint": "Configure schwab.token_json in admin credentials."},
        )

    async def _get_client(self) -> Any:
        if self._paused:
            raise ProviderConnectionError("Schwab provider paused - re-authorization required")
        if self._client is not None:
            return self._client

        async with self._get_client_lock():
            if self._paused:
                raise ProviderConnectionError("Schwab provider paused - re-authorization required")
            if self._client is not None:
                return self._client

            client_factory = easy_client
            if client_factory is None:
                raise ProviderConnectionError(
                    "schwab-py is not installed. Install dependencies and retry.",
                    details={"dependency": "schwab-py"},
                )

            key_value, secret_value = await self._get_credentials()
            token_path = await self._resolve_token_path()

            def _create_client() -> Any:
                # easy_client() is a synchronous factory: reads the token file and
                # returns an async httpx client when asyncio=True. It does NOT perform
                # network I/O during construction, so asyncio.to_thread is safe here.
                return client_factory(
                    api_key=key_value,
                    app_secret=secret_value,
                    callback_url=settings.SCHWAB_CALLBACK_URL,
                    token_path=token_path,
                    asyncio=settings.SCHWAB_ASYNCIO,
                )

            try:
                self._client = await asyncio.to_thread(_create_client)
            except FileNotFoundError:
                self._cleanup_temp_token_file()
                raise ProviderConnectionError(
                    "Schwab token not found. Re-authorize Schwab through the admin UI.",
                    details={"hint": "Configure schwab.token_json in admin credentials."},
                )
            except Exception as exc:
                self._cleanup_temp_token_file()
                raise ProviderConnectionError(
                    "Failed to authenticate with Schwab. Re-authorize through the admin UI.",
                    details={"hint": f"Auth error: {type(exc).__name__}"},
                ) from exc

        return self._client

    async def _check_rate_limit(self) -> None:
        """Sliding-window rate limiter — async-safe via asyncio.Lock."""
        limit = self.rate_limit_per_sec
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

    def _parse_option_chain(
        self,
        symbol: str,
        data: dict,
        expiry: date,
        min_strike: Optional[Decimal],
        max_strike: Optional[Decimal],
    ) -> list[OptionQuote]:
        options: list[OptionQuote] = []

        option_maps: tuple[tuple[Literal["call", "put"], str], ...] = (
            ("call", "callExpDateMap"),
            ("put", "putExpDateMap"),
        )

        for option_type, map_key in option_maps:
            exp_date_map = data.get(map_key)
            if not isinstance(exp_date_map, dict):
                continue

            for exp_date_key, strike_map in exp_date_map.items():
                try:
                    exp_date = date.fromisoformat(str(exp_date_key).split(":", 1)[0])
                except ValueError:
                    continue

                if exp_date != expiry:
                    continue
                if not isinstance(strike_map, dict):
                    continue

                for contracts in strike_map.values():
                    if not isinstance(contracts, list) or not contracts:
                        continue
                    contract = contracts[0]
                    if not isinstance(contract, dict):
                        continue

                    strike_raw = contract.get("strikePrice")
                    if strike_raw is None:
                        continue

                    strike = Decimal(str(strike_raw))
                    if min_strike is not None and strike < min_strike:
                        continue
                    if max_strike is not None and strike > max_strike:
                        continue

                    last = contract.get("last")
                    mark = contract.get("mark")
                    price_raw = last or mark
                    if price_raw is None:
                        continue

                    symbol_value = contract.get("symbol") or contract.get("description") or ""
                    options.append(
                        OptionQuote(
                            symbol=str(symbol_value),
                            underlying_symbol=symbol,
                            strike=strike,
                            expiry=expiry,
                            type=option_type,
                            price=Decimal(str(price_raw)),
                            bid=Decimal(str(contract["bid"])) if contract.get("bid") is not None else None,
                            ask=Decimal(str(contract["ask"])) if contract.get("ask") is not None else None,
                            volume=int(contract["totalVolume"]) if contract.get("totalVolume") is not None else None,
                            open_interest=int(contract["openInterest"]) if contract.get("openInterest") is not None else None,
                            implied_volatility=contract.get("volatility"),  # Schwab uses "volatility" for IV.
                            delta=contract.get("delta"),
                            gamma=contract.get("gamma"),
                            theta=contract.get("theta"),
                            vega=contract.get("vega"),
                            provider="schwab",
                        )
                    )

        return sorted(options, key=lambda item: (item.type, item.strike))

    def _mark_paused(self) -> bool:
        was_initialized = self._client is not None
        if was_initialized:
            self._paused = True
        self._client = None
        return was_initialized

    async def _handle_error_status(self, status_code: int, symbol: str, context: str) -> None:
        """Map Schwab HTTP error codes to appropriate AppError types."""
        if status_code == _HTTP_RATE_LIMITED:
            raise ProviderTimeoutError("schwab", details={"status_code": status_code})
        if status_code in (_HTTP_UNAUTHORIZED, _HTTP_FORBIDDEN):
            was_initialized = self._mark_paused()
            if was_initialized:
                await self._fire_webhook("Schwab token expired - re-authorization required via MDH Admin UI")
            raise ProviderConnectionError(
                "Schwab token has expired or is invalid. Re-authorize through the admin UI.",
                details={"hint": "Token rotation required every 7 days."},
            )
        raise ProviderError(
            f"Schwab {context} request failed for {symbol}.",
            details={"status_code": status_code},
        )

    async def _fire_webhook(self, message: str) -> None:
        webhook_url = await self._load_repository_credential("alert_webhook_url")
        if not webhook_url:
            return
        try:
            validate_webhook_url(webhook_url)
        except ValueError:
            logger.warning("Skipping Schwab webhook with unsafe URL")
            return

        try:
            from app.admin.runtime import get_provider_config_repository
            repo = get_provider_config_repository()
            config = await repo.get("schwab")
            webhook_format = config.connection_config.get("alert_webhook_format", "slack") if config.connection_config else "slack"
        except Exception:
            webhook_format = settings.SCHWAB_ALERT_WEBHOOK_FORMAT

        if webhook_format == "discord":
            payload = {"content": message}
        elif webhook_format == "slack":
            payload = {"text": message}
        else:
            payload = {"message": message}

        try:
            import httpx

            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                response = await client.post(webhook_url, json=payload)
                response.raise_for_status()
        except Exception:
            logger.warning("Failed to send Schwab token-expiry webhook", exc_info=True)

    def _map_schwab_option_http_error(self, status_code: int, symbol: str, context: str) -> None:
        if status_code == _HTTP_UNAUTHORIZED:
            raise ProviderConnectionError(
                f"Schwab {context} request unauthorized for {symbol}.",
                details={"status_code": status_code},
            )
        if status_code == _HTTP_FORBIDDEN:
            raise ProviderConnectionError(
                f"Schwab {context} request forbidden for {symbol}.",
                details={"status_code": status_code},
            )
        if status_code == _HTTP_RATE_LIMITED:
            raise ProviderTimeoutError("schwab", details={"status_code": status_code})
        raise ProviderError(
            f"Schwab {context} request failed for {symbol}.",
            details={"status_code": status_code},
        )

    @staticmethod
    def _parse_occ_symbol(option_id: str) -> tuple[str, date, Literal["call", "put"], Decimal]:
        match = _OCC_OPTION_SYMBOL_RE.match(option_id)
        if not match:
            raise AppError(f"Invalid option symbol: {option_id}", "INVALID_PROVIDER", details={"status_code": 400})

        underlying = match.group(1)
        expiry = datetime.strptime(match.group(2), "%y%m%d").date()
        right = "call" if match.group(3) == "C" else "put"
        strike = Decimal(match.group(4)) / Decimal("1000")
        return underlying, expiry, right, strike

    def unpause(self) -> None:
        self._paused = False
        self._client = None
        self._cleanup_temp_token_file()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def test_connection(self) -> dict:
        """Validate Schwab OAuth token with a lightweight account request."""
        try:
            await self._check_rate_limit()
            client = await self._get_client()
            response = await asyncio.wait_for(
                client.get_accounts(),
                timeout=self.timeout_seconds,
            )

            if response.status_code == _HTTP_OK:
                return {
                    "status_code": 200,
                    "success": True,
                    "message": "Schwab OAuth token valid",
                    "details": {"endpoint": "get_accounts"},
                }

            if response.status_code in (_HTTP_UNAUTHORIZED, _HTTP_FORBIDDEN):
                self._mark_paused()
                return {
                    "status_code": 401,
                    "success": False,
                    "message": "Schwab OAuth token expired or invalid",
                    "details": {"status_code": response.status_code},
                }

            return {
                "status_code": 503,
                "success": False,
                "message": "Schwab service unavailable",
                "details": {"status_code": response.status_code},
            }
        except asyncio.TimeoutError:
            return {
                "status_code": 503,
                "success": False,
                "message": "Schwab service unavailable",
                "details": {"reason": "timeout", "timeout_seconds": self.timeout_seconds},
            }
        except Exception as exc:
            error_message = str(exc)
            lowered = error_message.lower()
            if any(token in lowered for token in ("token", "unauthor", "forbidden", "expired", "invalid")):
                return {
                    "status_code": 401,
                    "success": False,
                    "message": "Schwab OAuth token expired or invalid",
                    "details": {"error": error_message},
                }
            return {
                "status_code": 503,
                "success": False,
                "message": "Schwab service unavailable",
                "details": {"error": error_message},
            }

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
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            raise ProviderTimeoutError(
                "schwab",
                details={"reason": "request timeout", "timeout_seconds": self.timeout_seconds},
            )

        if response.status_code != _HTTP_OK:
            await self._handle_error_status(response.status_code, symbol, "historical price")

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
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            raise ProviderTimeoutError(
                "schwab",
                details={"reason": "request timeout", "timeout_seconds": self.timeout_seconds},
            )

        if response.status_code != _HTTP_OK:
            await self._handle_error_status(response.status_code, symbol, "quote")

        return self._parse_quote(symbol, response.json())

    async def get_option_chain(
        self,
        symbol: str,
        expiry: date,
        min_strike: Optional[Decimal] = None,
        max_strike: Optional[Decimal] = None,
        right: Optional[Literal["call", "put"]] = None,
        market_data_type: Optional[int] = None,
    ) -> OptionChain:
        del market_data_type  # Schwab options endpoint does not expose data-type selection.

        client = await self._get_client()

        contract_type: Any = {None: "ALL", "call": "CALL", "put": "PUT"}[right]
        options_ns = getattr(type(client), "Options", None)
        contract_type_enum = getattr(options_ns, "ContractType", None) if options_ns is not None else None
        if contract_type_enum is not None:
            contract_type = {
                None: contract_type_enum.ALL,
                "call": contract_type_enum.CALL,
                "put": contract_type_enum.PUT,
            }[right]

        response = await asyncio.to_thread(
            client.get_option_chain,
            symbol,
            contract_type=contract_type,
            from_date=expiry,
            to_date=expiry,
        )

        if response.status_code != _HTTP_OK:
            self._map_schwab_option_http_error(response.status_code, symbol, "option chain")

        options = self._parse_option_chain(symbol, response.json(), expiry, min_strike, max_strike)
        if right is not None:
            options = [option for option in options if option.type == right]
        return OptionChain(underlying_symbol=symbol, expiry=expiry, options=options, provider="schwab")

    async def get_option_quote(
        self,
        symbol: str,
        option_id: str,
        market_data_type: Optional[int] = None,
    ) -> OptionQuote:
        del market_data_type  # Schwab options endpoint does not expose data-type selection.

        client = await self._get_client()
        response = await asyncio.to_thread(client.get_quotes, [option_id])

        if response.status_code != _HTTP_OK:
            self._map_schwab_option_http_error(response.status_code, symbol, "option quote")

        payload = response.json()
        entry = payload.get(option_id)
        if entry is None:
            raise DataNotFoundError("OptionContract", option_id)

        quote = entry.get("quote", entry) if isinstance(entry, dict) else {}
        if not isinstance(quote, dict):
            raise DataNotFoundError("OptionContract", option_id)

        delta = quote.get("delta")
        gamma = quote.get("gamma")
        theta = quote.get("theta")
        vega = quote.get("vega")

        if all(greek is None for greek in (delta, gamma, theta, vega)):
            parsed_underlying, parsed_expiry, parsed_right, parsed_strike = self._parse_occ_symbol(option_id)
            chain = await self.get_option_chain(
                symbol=parsed_underlying,
                expiry=parsed_expiry,
                min_strike=parsed_strike,
                max_strike=parsed_strike,
                right=parsed_right,
            )
            matches = [opt for opt in chain.options if opt.type == parsed_right and opt.strike == parsed_strike]
            if not matches:
                raise DataNotFoundError("OptionContract", option_id)
            return matches[0]

        parsed_underlying, parsed_expiry, parsed_right, parsed_strike = self._parse_occ_symbol(option_id)
        parsed_right = cast(Literal["call", "put"], parsed_right)
        last = quote.get("lastPrice", quote.get("last"))
        mark = quote.get("mark")
        price_raw = last or mark
        if price_raw is None:
            raise DataNotFoundError("OptionQuote", option_id)

        return OptionQuote(
            symbol=option_id,
            underlying_symbol=symbol or parsed_underlying,
            strike=Decimal(str(quote.get("strikePrice", parsed_strike))),
            expiry=parsed_expiry,
            type=parsed_right,
            price=Decimal(str(price_raw)),
            bid=Decimal(str(quote["bidPrice"])) if quote.get("bidPrice") is not None else None,
            ask=Decimal(str(quote["askPrice"])) if quote.get("askPrice") is not None else None,
            volume=int(quote["totalVolume"]) if quote.get("totalVolume") is not None else None,
            open_interest=int(quote["openInterest"]) if quote.get("openInterest") is not None else None,
            implied_volatility=quote.get("volatility"),
            delta=delta,
            gamma=gamma,
            theta=theta,
            vega=vega,
            provider="schwab",
        )

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
                self._cleanup_temp_token_file()
