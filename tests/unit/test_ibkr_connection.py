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

from unittest.mock import AsyncMock, patch

import pytest

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


def _runtime_config(**connection_config):
    from app.admin.provider_config_repository import ProviderRuntimeConfig

    return ProviderRuntimeConfig(
        provider_name="ibkr",
        enabled=True,
        timeout_seconds=10.0,
        retry_count=3,
        retry_backoff_seconds=0.5,
        rate_limit_per_sec=0.0,
        circuit_breaker_enabled=False,
        circuit_breaker_failure_threshold=5,
        circuit_breaker_reset_seconds=60.0,
        connection_config=connection_config,
    )


def test_configure_applies_gateway_connection_config(ibkr_provider):
    provider, mock_ib = ibkr_provider
    mock_ib.isConnected.return_value = False

    provider.configure(
        _runtime_config(
            host="192.168.1.12", port="4002", client_id=815, market_data_type=2
        )
    )

    assert provider.host == "192.168.1.12"
    assert provider.port == 4002
    assert provider.client_id == 815
    assert provider.market_data_type == 2
    mock_ib.disconnect.assert_not_called()


def test_configure_keeps_defaults_for_missing_or_invalid_values(ibkr_provider):
    provider, _ = ibkr_provider
    default = (provider.host, provider.port, provider.client_id)

    provider.configure(_runtime_config(host="  ", port="abc", client_id=None))

    assert (provider.host, provider.port, provider.client_id) == default


def test_configure_disconnects_when_endpoint_changes(ibkr_provider):
    provider, mock_ib = ibkr_provider
    mock_ib.isConnected.return_value = True
    provider._connected = True

    provider.configure(_runtime_config(host="192.168.1.12", port=4002))

    mock_ib.disconnect.assert_called_once()
    assert provider._connected is False


def test_configure_keeps_connection_when_endpoint_unchanged(ibkr_provider):
    provider, mock_ib = ibkr_provider
    mock_ib.isConnected.return_value = True

    provider.configure(_runtime_config(host=provider.host, port=provider.port))

    mock_ib.disconnect.assert_not_called()


@pytest.mark.asyncio
async def test_test_connection_uses_configured_gateway(ibkr_provider):
    provider, mock_ib = ibkr_provider
    mock_ib.isConnected.return_value = False
    mock_ib.connectAsync = AsyncMock()

    provider.configure(_runtime_config(host="192.168.1.12", port=4002, client_id=815))
    result = await provider.test_connection()

    mock_ib.connectAsync.assert_awaited_once_with("192.168.1.12", 4002, 815)
    assert result["success"] is True
