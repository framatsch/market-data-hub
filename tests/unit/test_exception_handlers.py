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
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, AsyncMock
from app.main import app
from app.utils.errors import DataNotFoundError, ProviderError, InvalidProviderError

@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)

def test_data_not_found_handler(client):
    with pytest.MonkeyPatch.context() as m:
        # We need a route that throws AppError
        from app.api.routes_prices import router
        @router.get("/test-error-404")
        async def mock_error_404():
            raise DataNotFoundError("Test", "123")
        
        # Note: router is already included in app, but we can't easily re-include it
        # Let's mock a service instead
        from app.dependencies import get_price_service
        mock_service = MagicMock()
        mock_service.get_latest_price = AsyncMock(side_effect=DataNotFoundError("Test", "123"))
        app.dependency_overrides[get_price_service] = lambda: mock_service
        
        response = client.get("/prices/MISSING/last")
        assert response.status_code == 404
        app.dependency_overrides.clear()

def test_invalid_provider_handler(client):
    from app.dependencies import get_price_service
    mock_service = MagicMock()
    mock_service.get_latest_price = AsyncMock(side_effect=InvalidProviderError("bad"))
    app.dependency_overrides[get_price_service] = lambda: mock_service
    
    response = client.get("/prices/AAPL/last?provider=bad")
    assert response.status_code == 400
    app.dependency_overrides.clear()

def test_provider_not_available_handler(client):
    from app.dependencies import get_price_service
    mock_service = MagicMock()
    mock_service.get_latest_price = AsyncMock(side_effect=ProviderError("unavailable", code="PROVIDER_NOT_AVAILABLE"))
    app.dependency_overrides[get_price_service] = lambda: mock_service
    
    response = client.get("/prices/AAPL/last")
    assert response.status_code == 503
    app.dependency_overrides.clear()

def test_generic_exception_handler(client):
    from app.dependencies import get_price_service
    mock_service = MagicMock()
    mock_service.get_latest_price = AsyncMock(side_effect=Exception("Uncaught"))
    app.dependency_overrides[get_price_service] = lambda: mock_service
    
    response = client.get("/prices/AAPL/last")
    assert response.status_code == 500
    app.dependency_overrides.clear()

