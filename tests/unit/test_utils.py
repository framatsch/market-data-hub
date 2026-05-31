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

import pytest
from pydantic import SecretStr
from app.utils.secrets import unwrap_secret
from app.utils.errors import (
    AppError, ProviderError, DataNotFoundError, 
    ProviderConnectionError, DataValidationError
)

def test_unwrap_secret():
    assert unwrap_secret("plain") == "plain"
    assert unwrap_secret(SecretStr("secret")) == "secret"
    assert unwrap_secret(None) is None

def test_app_errors():
    err = AppError("msg", "CODE", {"detail": "info"})
    assert err.message == "msg"
    assert err.code == "CODE"
    assert err.details == {"detail": "info"}

    assert ProviderError("msg").code == "PROVIDER_ERROR"
    assert DataNotFoundError("Entity", "ID").code == "DATA_NOT_FOUND"
    assert ProviderConnectionError("msg").code == "PROVIDER_CONNECTION_ERROR"
    assert DataValidationError("msg").code == "DATA_VALIDATION_ERROR"

def test_specific_errors():
    from app.utils.errors import InvalidProviderError, ProviderTimeoutError, ProviderNotAvailableError
    assert InvalidProviderError("name").code == "INVALID_PROVIDER"
    assert ProviderTimeoutError("msg").code == "PROVIDER_TIMEOUT"
    assert ProviderNotAvailableError("msg").code == "PROVIDER_NOT_AVAILABLE"

def test_map_httpx_http_error():
    import httpx
    from unittest.mock import MagicMock
    from app.utils.errors import map_httpx_http_error, DataNotFoundError, ProviderNotAvailableError
    
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 404
    mock_response.text = "Not Found"
    error = httpx.HTTPStatusError("msg", request=MagicMock(), response=mock_response)
    
    mapped = map_httpx_http_error(provider="test", error=error, entity="Entity", identifier="ID")
    assert isinstance(mapped, DataNotFoundError)
    assert mapped.details["provider"] == "test"
    
    mock_response.status_code = 403
    mapped = map_httpx_http_error(provider="test", error=error, entity="Entity", identifier="ID")
    assert isinstance(mapped, ProviderNotAvailableError)
    
    mock_response.status_code = 500
    mapped = map_httpx_http_error(provider="test", error=error, entity="Entity", identifier="ID")
    assert mapped.code == "PROVIDER_CONNECTION_ERROR"
    
    mock_response.status_code = 400
    mapped = map_httpx_http_error(provider="test", error=error, entity="Entity", identifier="ID")
    assert mapped.code == "PROVIDER_ERROR"

def test_error_response_models():
    from app.utils.errors import ErrorDetail, ErrorResponse
    detail = ErrorDetail(code="TEST", message="Test message", details={"a": 1})
    resp = ErrorResponse(error=detail)
    assert resp.error.code == "TEST"




