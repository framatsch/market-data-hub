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
