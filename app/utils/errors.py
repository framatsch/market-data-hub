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

from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel


class AppError(Exception):
    """Base class for application errors."""

    def __init__(self, message: str, code: str, details: dict[str, Any] | None = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)


class ProviderError(AppError):
    def __init__(
        self,
        message: str,
        code: str = "PROVIDER_ERROR",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message, code, details)


class ProviderConnectionError(ProviderError):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, "PROVIDER_CONNECTION_ERROR", details)


class ProviderNotAvailableError(AppError):
    def __init__(self, provider: str, details: dict[str, Any] | None = None):
        super().__init__(
            f"Provider '{provider}' is not available.",
            "PROVIDER_NOT_AVAILABLE",
            details,
        )


class ProviderNotEntitledError(ProviderError):
    """The provider denied access because the subscription does not cover the data."""

    def __init__(
        self,
        provider: str,
        *,
        symbol: str | None = None,
        instrument: str | None = None,
        provider_message: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        merged: dict[str, Any] = {"provider": provider}
        if symbol is not None:
            merged["symbol"] = symbol
        if instrument is not None:
            merged["instrument"] = instrument
        if provider_message:
            merged["provider_message"] = str(provider_message)[:500]
        merged.update(details or {})
        super().__init__(
            f"The subscription at provider '{provider}' does not cover the requested "
            "instrument or data.",
            "PROVIDER_NOT_ENTITLED",
            merged,
        )


def not_entitled(
    provider: str,
    root: str,
    sec_type: str,
    *,
    instrument: str | None = None,
    message: object = None,
) -> ProviderNotEntitledError:
    """Build the uniform not-entitled error from a provider's root and type."""
    from app.utils.symbols import canonical_symbol

    return ProviderNotEntitledError(
        provider,
        symbol=canonical_symbol(root, sec_type),
        instrument=instrument,
        provider_message=None if message is None else str(message),
    )


class ProviderTimeoutError(AppError):
    def __init__(self, provider: str, details: dict[str, Any] | None = None):
        super().__init__(
            f"Request to provider '{provider}' timed out.", "PROVIDER_TIMEOUT", details
        )


class InvalidProviderError(AppError):
    def __init__(self, provider: str, details: dict[str, Any] | None = None):
        super().__init__(
            f"Invalid provider: '{provider}'.", "INVALID_PROVIDER", details
        )


class CapabilityNotSupportedError(AppError):
    def __init__(
        self,
        provider: str,
        operation: str,
        *,
        sec_type: str,
        supported: list[str] | list[int],
        tenor_days: int | None = None,
    ):
        super().__init__(
            f"Provider '{provider}' does not support the requested {operation}.",
            "CAPABILITY_NOT_SUPPORTED",
            {
                "provider": provider,
                "operation": operation,
                "sec_type": sec_type,
                "tenor_days": tenor_days,
                "supported": supported,
            },
        )


class DataNotFoundError(AppError):
    def __init__(
        self, entity: str, identifier: str, details: dict[str, Any] | None = None
    ):
        super().__init__(
            f"{entity} with id '{identifier}' not found.", "DATA_NOT_FOUND", details
        )


class DataValidationError(AppError):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, "DATA_VALIDATION_ERROR", details)


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = {}


class ErrorResponse(BaseModel):
    error: ErrorDetail


def map_httpx_http_error(
    *,
    provider: str,
    error: httpx.HTTPStatusError,
    entity: str,
    identifier: str,
    classify_forbidden: Callable[[httpx.HTTPStatusError], bool] | None = None,
    symbol: str | None = None,
    instrument: str | None = None,
) -> AppError:
    """Map HTTP status errors from providers to internal AppError types.

    HTTP 401 always means a credential failure. HTTP 403 is a credential failure
    too unless `classify_forbidden` says the response is a missing entitlement.
    """
    status_code = error.response.status_code
    details = {
        "provider": provider,
        "status_code": status_code,
    }

    response_text = error.response.text
    if response_text:
        details["response"] = response_text[:500]

    if status_code == 404:
        return DataNotFoundError(entity, identifier, details=details)
    if (
        status_code == 403
        and classify_forbidden is not None
        and classify_forbidden(error)
    ):
        return ProviderNotEntitledError(
            provider,
            symbol=symbol or identifier,
            instrument=instrument,
            provider_message=response_text,
            details={"status_code": status_code},
        )
    if status_code in (401, 403):
        return ProviderNotAvailableError(provider, details=details)
    if status_code == 429:
        return ProviderTimeoutError(provider, details=details)
    if status_code >= 500:
        return ProviderConnectionError(
            f"Provider '{provider}' returned server error {status_code}.",
            details=details,
        )

    return ProviderError(
        f"Provider '{provider}' returned HTTP {status_code}.",
        details=details,
    )
