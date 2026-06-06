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
from unittest.mock import patch, MagicMock, AsyncMock
from app.providers.ibkr import IBKRProvider
from app.utils.errors import ProviderConnectionError

@pytest.fixture
def ibkr_provider():
    with patch("app.providers.ibkr.IB") as mock_ib:
        provider = IBKRProvider()
        yield provider, mock_ib.return_value

@pytest.mark.asyncio
async def test_ensure_connection_success(ibkr_provider):
    provider, mock_ib = ibkr_provider
    mock_ib.isConnected.return_value = True
    
    await provider._ensure_connection()
    mock_ib.connectAsync.assert_not_called()

@pytest.mark.asyncio
async def test_ensure_connection_retry_fail(ibkr_provider, monkeypatch):
    provider, mock_ib = ibkr_provider
    mock_ib.isConnected.return_value = False
    mock_ib.connectAsync = AsyncMock(side_effect=Exception("Conn Fail"))
    
    # Speed up test
    with patch("app.providers.ibkr.asyncio.sleep", AsyncMock()):
        with pytest.raises(ProviderConnectionError):
            await provider._ensure_connection()
    
    assert mock_ib.connectAsync.called


@pytest.mark.asyncio
async def test_test_connection_success_when_already_connected(ibkr_provider):
    provider, mock_ib = ibkr_provider
    mock_ib.isConnected.return_value = True

    result = await provider.test_connection()

    assert result["status_code"] == 200
    assert result["success"] is True
    assert result["message"] == "Connected to IBKR"


@pytest.mark.asyncio
async def test_test_connection_auth_failure(ibkr_provider):
    provider, mock_ib = ibkr_provider
    mock_ib.isConnected.return_value = False
    mock_ib.connectAsync = AsyncMock(side_effect=Exception("Unauthorized"))

    result = await provider.test_connection()

    assert result["status_code"] == 401
    assert result["success"] is False
    assert result["message"] == "Authentication failed"


@pytest.mark.asyncio
async def test_test_connection_unreachable_failure(ibkr_provider):
    provider, mock_ib = ibkr_provider
    mock_ib.isConnected.return_value = False
    mock_ib.connectAsync = AsyncMock(side_effect=Exception("Connection refused"))

    result = await provider.test_connection()

    assert result["status_code"] == 503
    assert result["success"] is False
    assert result["message"] == "IBKR TWS/Gateway not reachable"
