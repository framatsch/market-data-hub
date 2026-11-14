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

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ib_async import StartupFetch

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

    mock_ib.connectAsync.assert_awaited_once_with(
        "192.168.1.12", 4002, 815, fetchFields=StartupFetch(0)
    )
    assert result["success"] is True


@pytest.mark.asyncio
async def test_concurrent_requests_connect_only_once(ibkr_provider):
    provider, mock_ib = ibkr_provider
    state = {"connected": False}
    mock_ib.isConnected.side_effect = lambda: state["connected"]

    async def slow_connect(*args, **kwargs):
        await asyncio.sleep(0.05)
        state["connected"] = True

    mock_ib.connectAsync = AsyncMock(side_effect=slow_connect)

    await asyncio.gather(*(provider._ensure_connection() for _ in range(5)))

    assert mock_ib.connectAsync.await_count == 1


@pytest.mark.asyncio
async def test_connect_skips_startup_sync(ibkr_provider):
    provider, mock_ib = ibkr_provider
    mock_ib.isConnected.return_value = False
    mock_ib.connectAsync = AsyncMock()

    await provider._ensure_connection()

    kwargs = mock_ib.connectAsync.await_args.kwargs
    assert kwargs["fetchFields"] == StartupFetch(0)


@pytest.mark.asyncio
async def test_error_handler_registered_once_across_reconnects(ibkr_provider):
    provider, mock_ib = ibkr_provider
    mock_ib.isConnected.return_value = False
    mock_ib.connectAsync = AsyncMock()
    mock_ib.errorEvent = MagicMock()
    mock_ib.errorEvent.__iadd__.return_value = mock_ib.errorEvent

    for _ in range(3):
        await provider._ensure_connection()

    assert mock_ib.errorEvent.__iadd__.call_count == 1


@pytest.mark.asyncio
async def test_failed_connect_closes_socket(ibkr_provider):
    provider, mock_ib = ibkr_provider
    mock_ib.isConnected.return_value = False
    mock_ib.connectAsync = AsyncMock(side_effect=TimeoutError())

    with pytest.raises(ProviderConnectionError):
        await provider._ensure_connection()

    mock_ib.disconnect.assert_called()
    assert provider._connected is False


@pytest.mark.asyncio
async def test_client_id_conflict_is_reported_clearly(ibkr_provider):
    provider, mock_ib = ibkr_provider
    mock_ib.isConnected.return_value = False

    async def conflicting_connect(*args, **kwargs):
        provider._on_ib_error(
            -1, 326, "Unable to connect as the client id is already in use.", None
        )
        raise TimeoutError()

    mock_ib.connectAsync = AsyncMock(side_effect=conflicting_connect)

    with pytest.raises(ProviderConnectionError) as exc_info:
        await provider._ensure_connection()

    message = str(exc_info.value)
    assert "client id" in message
    assert "326" in message


@pytest.mark.asyncio
async def test_empty_connect_error_still_names_exception(ibkr_provider):
    provider, mock_ib = ibkr_provider
    mock_ib.isConnected.return_value = False
    mock_ib.connectAsync = AsyncMock(side_effect=TimeoutError())

    with pytest.raises(ProviderConnectionError) as exc_info:
        await provider._ensure_connection()

    assert "TimeoutError" in str(exc_info.value)
