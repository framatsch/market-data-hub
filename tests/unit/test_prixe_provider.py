from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.config import settings
from app.providers.prixe import PrixeProvider
from app.utils.errors import DataNotFoundError, ProviderError


@pytest.fixture(autouse=True)
def restore_prixe_settings():
    saved_key = settings.PRIXE_API_KEY
    saved_base_url = settings.PRIXE_BASE_URL
    settings.PRIXE_API_KEY = "test-prixe-key"
    settings.PRIXE_BASE_URL = "https://api.prixe.io"
    yield
    settings.PRIXE_API_KEY = saved_key
    settings.PRIXE_BASE_URL = saved_base_url


@pytest.mark.asyncio
async def test_get_last_price_success_maps_decimal_fields():
    with patch("app.providers.prixe.httpx.AsyncClient") as mock_async_client:
        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            return_value=httpx.Response(
                200,
                request=httpx.Request("POST", "https://api.prixe.io/api/last_sold"),
                json={
                    "data": {
                        "symbol": "aapl",
                        "last_sold": "189.45",
                        "bid": "189.40",
                        "ask": "189.50",
                        "currency": "usd",
                        "timestamp": "2026-05-31T12:00:00Z",
                    }
                },
            )
        )
        mock_client.aclose = AsyncMock()
        mock_async_client.return_value = mock_client

        provider = PrixeProvider()
        quote = await provider.get_last_price("aapl")

        assert quote.symbol == "AAPL"
        assert quote.price == Decimal("189.45")
        assert quote.bid == Decimal("189.40")
        assert quote.ask == Decimal("189.50")
        assert quote.currency == "USD"
        assert quote.provider == "prixe"

        mock_client.post.assert_awaited_once_with("/api/last_sold", json={"symbol": "AAPL"})
        await provider.close()
        mock_client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_last_price_404_maps_to_data_not_found():
    with patch("app.providers.prixe.httpx.AsyncClient") as mock_async_client:
        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            return_value=httpx.Response(
                404,
                request=httpx.Request("POST", "https://api.prixe.io/api/last_sold"),
                json={"detail": "ticker not found"},
            )
        )
        mock_client.aclose = AsyncMock()
        mock_async_client.return_value = mock_client

        provider = PrixeProvider()
        with pytest.raises(DataNotFoundError):
            await provider.get_last_price("UNKNOWN")


def test_missing_api_key_raises_provider_not_available():
    settings.PRIXE_API_KEY = ""
    with pytest.raises(ProviderError) as exc_info:
        PrixeProvider()

    assert exc_info.value.code == "PROVIDER_NOT_AVAILABLE"


@pytest.mark.asyncio
async def test_get_historical_prices_maps_to_price_bars():
    with patch("app.providers.prixe.httpx.AsyncClient") as mock_async_client:
        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            return_value=httpx.Response(
                200,
                request=httpx.Request("POST", "https://api.prixe.io/api/price"),
                json={
                    "success": True,
                    "data": {
                        "ticker": "MSFT",
                        "timestamp": [1714521600, 1714608000],
                        "open": [400.0, 401.0],
                        "high": [405.0, 406.0],
                        "low": [398.0, 399.0],
                        "close": [404.0, 405.0],
                        "volume": [1200, 1300],
                    },
                },
            )
        )
        mock_client.aclose = AsyncMock()
        mock_async_client.return_value = mock_client

        provider = PrixeProvider()
        start = datetime(2024, 5, 1, tzinfo=timezone.utc)
        end = datetime(2024, 5, 3, tzinfo=timezone.utc)

        bars = await provider.get_historical_prices("msft", "1d", start, end)

        assert len(bars) == 2
        assert bars[0].symbol == "MSFT"
        assert bars[0].open == Decimal("400.0")
        assert bars[0].close == Decimal("404.0")
        assert bars[0].provider == "prixe"

        mock_client.post.assert_awaited_once_with(
            "/api/price",
            json={
                "ticker": "MSFT",
                "start_date": "2024-05-01",
                "end_date": "2024-05-03",
                "interval": "1d",
            },
        )


@pytest.mark.asyncio
async def test_get_historical_prices_rejects_unsupported_interval():
    with patch("app.providers.prixe.httpx.AsyncClient") as mock_async_client:
        mock_client = MagicMock()
        mock_client.post = AsyncMock()
        mock_client.aclose = AsyncMock()
        mock_async_client.return_value = mock_client

        provider = PrixeProvider()
        start = datetime(2024, 5, 1, tzinfo=timezone.utc)
        end = datetime(2024, 5, 3, tzinfo=timezone.utc)

        with pytest.raises(ProviderError) as exc_info:
            await provider.get_historical_prices("MSFT", "2h", start, end)

        assert "Unsupported Prixe interval" in exc_info.value.message
        mock_client.post.assert_not_called()


@pytest.mark.asyncio
async def test_test_connection_success():
    with patch("app.providers.prixe.httpx.AsyncClient") as mock_async_client:
        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            return_value=httpx.Response(
                200,
                request=httpx.Request("POST", "https://api.prixe.io/api/last_sold"),
                json={"data": {"symbol": "AAPL", "last_sold": "100.0"}},
            )
        )
        mock_client.aclose = AsyncMock()
        mock_async_client.return_value = mock_client

        provider = PrixeProvider()
        result = await provider.test_connection()

        assert result["status_code"] == 200
        assert result["success"] is True
        assert result["message"] == "Prixe API key valid"


@pytest.mark.asyncio
async def test_test_connection_auth_failure():
    with patch("app.providers.prixe.httpx.AsyncClient") as mock_async_client:
        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            return_value=httpx.Response(
                401,
                request=httpx.Request("POST", "https://api.prixe.io/api/last_sold"),
                json={"detail": "unauthorized"},
            )
        )
        mock_client.aclose = AsyncMock()
        mock_async_client.return_value = mock_client

        provider = PrixeProvider()
        result = await provider.test_connection()

        assert result["status_code"] == 401
        assert result["success"] is False
        assert result["message"] == "Invalid Prixe API key"


@pytest.mark.asyncio
async def test_test_connection_service_unavailable():
    with patch("app.providers.prixe.httpx.AsyncClient") as mock_async_client:
        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=Exception("down"))
        mock_client.aclose = AsyncMock()
        mock_async_client.return_value = mock_client

        provider = PrixeProvider()
        result = await provider.test_connection()

        assert result["status_code"] == 503
        assert result["success"] is False
        assert result["message"] == "Prixe service unavailable"
