"""HTTP lifecycle, pacing, retries and a shared budget for metered providers."""

import asyncio
import logging
import time
from typing import Any

import httpx

from app.config import settings
from app.providers.base import _apply_runtime_config_defaults
from app.providers.credentials import get_provider_credential_sync
from app.providers.request_budget import BUDGET_DEFAULTS, RequestBudget
from app.utils.errors import (
    AppError,
    ProviderConnectionError,
    ProviderError,
    ProviderQuotaExhaustedError,
    ProviderTimeoutError,
    map_httpx_http_error,
)

logger = logging.getLogger(__name__)


class MeteredHttpProvider:
    name: str
    base_url: str
    minimum_spacing = 0.0

    def __init__(self) -> None:
        day, month = BUDGET_DEFAULTS[self.name]
        self.budget = RequestBudget(self.name, day, month)
        self.timeout_seconds = settings.PROVIDER_REQUEST_TIMEOUT
        self.retry_count = settings.PROVIDER_MAX_RETRIES
        self.retry_backoff_seconds = .5
        self.rate_limit_per_sec = 1.0 if self.minimum_spacing else 0.0
        self.connection_config: dict[str, Any] = {}
        self._client: httpx.AsyncClient | None = None
        self._request_lock = asyncio.Lock()
        self._last_sent = float("-inf")

    def configure(self, config: Any) -> None:
        self._runtime_config = config
        _apply_runtime_config_defaults(self, config)
        self.budget.configure(config.connection_config)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_seconds)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _auth(self, params: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        key = await asyncio.to_thread(get_provider_credential_sync, self.name, "api_key")
        return params, {"X-API-KEY": key}

    async def _decode(self, response: httpx.Response, symbol: str | None) -> Any:
        return response.json()

    def _http_error(self, error: httpx.HTTPStatusError, symbol: str | None) -> AppError:
        return map_httpx_http_error(provider=self.name, error=error, entity="Ticker", identifier=symbol or self.name)

    async def _request(self, path: str, params: dict[str, Any], symbol: str | None = None) -> Any:
        params, headers = await self._auth(params)
        client = await self._get_client()
        for attempt in range(self.retry_count + 1):
            try:
                async with self._request_lock:
                    spacing = max(self.minimum_spacing, 1 / self.rate_limit_per_sec if self.rate_limit_per_sec else 0)
                    delay = self._last_sent + spacing - time.monotonic()
                    if delay > 0:
                        await asyncio.sleep(delay)
                    await self.budget.consume()
                    try:
                        response = await client.get(path, params=params, headers=headers, timeout=self.timeout_seconds)
                    finally:
                        # Space requests from the previous *response*: differing latencies
                        # can otherwise land two requests inside one upstream second
                        # (observed live with Alpha Vantage at 1.05 s send spacing).
                        self._last_sent = time.monotonic()
                response.raise_for_status()
                return await self._decode(response, symbol)
            except httpx.HTTPStatusError as exc:
                error = self._http_error(exc, symbol)
                retryable = (exc.response.status_code == 429 or exc.response.status_code >= 500) and not (
                    isinstance(error, ProviderQuotaExhaustedError)
                )
            except httpx.TimeoutException:
                error = ProviderTimeoutError(self.name)
                retryable = True
            except httpx.RequestError:
                # Never include exception URLs: Alpha Vantage puts its key in the query.
                error = ProviderConnectionError(f"Request to provider '{self.name}' failed.")
                retryable = True
            except ProviderTimeoutError as exc:
                error = exc
                retryable = True
            except (ValueError, TypeError, KeyError) as exc:
                raise ProviderError(f"Invalid response from provider '{self.name}'.") from exc
            if not retryable or attempt == self.retry_count:
                raise error
            logger.warning(
                "Retrying %s request after %s (attempt %s/%s)",
                self.name, error.code, attempt + 1, self.retry_count,
            )
            retry_after = getattr(error, "retry_after", None)
            if retry_after is not None:
                await asyncio.sleep(min(float(retry_after), 30.0))
            else:
                await asyncio.sleep(max(self.minimum_spacing, self.retry_backoff_seconds * 2 ** attempt))
        raise ProviderError(f"Request to '{self.name}' failed")  # unreachable

    async def test_connection(self) -> dict[str, Any]:
        try:
            await self.get_last_price("AAPL")
            return {"status_code": 200, "success": True, "message": f"Connected to {self.name}", "details": {"ticker": "AAPL"}}
        except AppError as exc:
            status = 429 if exc.code == "PROVIDER_QUOTA_EXHAUSTED" else 503
            return {"status_code": status, "success": False, "message": exc.message, "details": exc.details}
