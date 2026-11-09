"""Prixe support declaration and 403 classification."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.providers.prixe import PrixeProvider
from app.utils.errors import ProviderNotAvailableError, ProviderNotEntitledError


def forbidden(text: str) -> httpx.Response:
    return httpx.Response(
        403,
        request=httpx.Request("POST", "https://api.prixe.io/api/last_sold"),
        text=text,
    )


@pytest.fixture
def provider():
    with patch("app.providers.prixe.httpx.AsyncClient") as client_class:
        client = MagicMock()
        client.post = AsyncMock()
        client.aclose = AsyncMock()
        client_class.return_value = client
        instance = PrixeProvider()
        instance._api_key = "key"
        yield instance


def test_keeps_stock_and_etf_defaults():
    assert PrixeProvider.price_sec_types == {"stock", "etf"}
    assert PrixeProvider.price_history_sec_types == {"stock", "etf"}


@pytest.mark.parametrize(
    "body",
    ["This endpoint requires the Pro+ plan", "Please upgrade your subscription"],
)
async def test_plan_restriction_is_not_entitled(provider, body):
    client = await provider._get_client()
    client.post.return_value = forbidden(body)
    with pytest.raises(ProviderNotEntitledError) as error:
        await provider.get_last_price("AAPL")
    assert error.value.code == "PROVIDER_NOT_ENTITLED"
    assert error.value.details["symbol"] == "AAPL"
    assert error.value.details["provider_message"] == body


async def test_history_plan_restriction_is_not_entitled(provider):
    client = await provider._get_client()
    client.post.return_value = forbidden("Upgrade your plan for intraday data")
    with pytest.raises(ProviderNotEntitledError):
        await provider.get_historical_prices(
            "AAPL", "1d", datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 11, 6, tzinfo=UTC)
        )


@pytest.mark.parametrize(
    "body",
    ["", "Forbidden", "Invalid API key", "Token expired; upgrade your key"],
)
async def test_credential_failures_stay_not_available(provider, body):
    client = await provider._get_client()
    client.post.return_value = forbidden(body)
    with pytest.raises(ProviderNotAvailableError):
        await provider.get_last_price("AAPL")


async def test_401_stays_not_available(provider):
    client = await provider._get_client()
    client.post.return_value = httpx.Response(
        401,
        request=httpx.Request("POST", "https://api.prixe.io/api/last_sold"),
        text="upgrade your plan",
    )
    with pytest.raises(ProviderNotAvailableError) as error:
        await provider.get_last_price("AAPL")
    assert error.value.code == "PROVIDER_NOT_AVAILABLE"
