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

from typing import Any, Dict, Optional
from pydantic import BaseModel

class AppError(Exception):
    """Base class for application errors."""
    def __init__(self, message: str, code: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)

class ProviderError(AppError):
    def __init__(self, message: str, code: str = "PROVIDER_ERROR", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, code, details)

class ProviderConnectionError(ProviderError):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, "PROVIDER_CONNECTION_ERROR", details)

class ProviderNotAvailableError(AppError):
    def __init__(self, provider: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(f"Provider '{provider}' is not available.", "PROVIDER_NOT_AVAILABLE", details)

class ProviderTimeoutError(AppError):
    def __init__(self, provider: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(f"Request to provider '{provider}' timed out.", "PROVIDER_TIMEOUT", details)

class InvalidProviderError(AppError):
    def __init__(self, provider: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(f"Invalid provider: '{provider}'.", "INVALID_PROVIDER", details)

class DataNotFoundError(AppError):
    def __init__(self, entity: str, identifier: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(f"{entity} with id '{identifier}' not found.", "DATA_NOT_FOUND", details)

class DataValidationError(AppError):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, "DATA_VALIDATION_ERROR", details)

class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Dict[str, Any] = {}

class ErrorResponse(BaseModel):
    error: ErrorDetail
