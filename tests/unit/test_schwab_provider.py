from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.config import settings
from app.providers.schwab import SchwabProvider
from app.utils.errors import DataNotFoundError, DataValidationError, ProviderConnectionError


class _Response:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


@pytest.fixture
def provider(monkeypatch, tmp_path: Path) -> SchwabProvider:
    token_file = tmp_path / "schwab_token.json"
    token_file.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(settings, "SCHWAB_API_KEY", "test-key")
    monkeypatch.setattr(settings, "SCHWAB_APP_SECRET", "test-secret")
    monkeypatch.setattr(settings, "SCHWAB_CALLBACK_URL", "https://127.0.0.1:8182")
    monkeypatch.setattr(settings, "SCHWAB_TOKEN_PATH", str(token_file))
    monkeypatch.setattr(settings, "SCHWAB_ASYNCIO", True)
    monkeypatch.setattr(settings, "SCHWAB_RATE_LIMIT_PER_SEC", 50)

    return SchwabProvider()


@pytest.mark.asyncio
async def test_get_historical_prices_daily_success(provider: SchwabProvider):
    client = Mock()
    client.get_price_history_every_day = AsyncMock(
        return_value=_Response(
            200,
            {
                "candles": [
                    {
                        "datetime": 1715731200000,
                        "open": 182.1,
                        "high": 183.2,
                        "low": 181.8,
                        "close": 182.63,
                        "volume": 1000,
                    }
                ]
            },
        )
    )

    provider._get_client = AsyncMock(return_value=client)

    start = datetime(2024, 5, 10, tzinfo=timezone.utc)
    end = datetime(2024, 5, 20, tzinfo=timezone.utc)
    bars = await provider.get_historical_prices("AAPL", "1d", start, end)

    assert len(bars) == 1
    assert bars[0].provider == "schwab"
    assert isinstance(bars[0].close, Decimal)
    assert bars[0].close == Decimal("182.63")


@pytest.mark.asyncio
async def test_get_historical_prices_intraday_success(provider: SchwabProvider):
    client = Mock()
    client.get_price_history_every_minute = AsyncMock(
        return_value=_Response(
            200,
            {
                "candles": [
                    {
                        "datetime": 1715731200000,
                        "open": 182.0,
                        "high": 182.3,
                        "low": 181.9,
                        "close": 182.1,
                        "volume": 150,
                    }
                ]
            },
        )
    )

    provider._get_client = AsyncMock(return_value=client)
    await provider.get_historical_prices(
        "AAPL",
        "1m",
        datetime(2024, 5, 15, tzinfo=timezone.utc),
        datetime(2024, 5, 16, tzinfo=timezone.utc),
    )

    client.get_price_history_every_minute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_historical_prices_unsupported_interval(provider: SchwabProvider):
    provider._get_client = AsyncMock(return_value=Mock())
    with pytest.raises(DataValidationError):
        await provider.get_historical_prices(
            "AAPL",
            "2h",
            datetime(2024, 5, 15, tzinfo=timezone.utc),
            datetime(2024, 5, 16, tzinfo=timezone.utc),
        )


@pytest.mark.asyncio
async def test_get_last_price_success(provider: SchwabProvider):
    client = Mock()
    client.get_quotes = AsyncMock(
        return_value=_Response(
            200,
            {
                "AAPL": {
                    "quote": {
                        "lastPrice": 182.63,
                        "bidPrice": 182.6,
                        "askPrice": 182.7,
                        "totalVolume": 12345,
                    }
                }
            },
        )
    )
    provider._get_client = AsyncMock(return_value=client)

    quote = await provider.get_last_price("AAPL")

    assert quote.provider == "schwab"
    assert quote.price == Decimal("182.63")


@pytest.mark.asyncio
async def test_get_last_price_unknown_symbol(provider: SchwabProvider):
    client = Mock()
    client.get_quotes = AsyncMock(return_value=_Response(200, {"MSFT": {"quote": {"lastPrice": 11.0}}}))
    provider._get_client = AsyncMock(return_value=client)

    with pytest.raises(DataNotFoundError):
        await provider.get_last_price("AAPL")


@pytest.mark.asyncio
async def test_provider_disabled_when_no_api_key(monkeypatch, tmp_path: Path):
    token_file = tmp_path / "token.json"
    token_file.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(settings, "SCHWAB_API_KEY", "")
    monkeypatch.setattr(settings, "SCHWAB_TOKEN_PATH", str(token_file))

    provider = SchwabProvider()

    with pytest.raises(ProviderConnectionError):
        await provider.get_last_price("AAPL")


@pytest.mark.asyncio
async def test_missing_token_file_raises_connection_error(monkeypatch, tmp_path: Path):
    missing = tmp_path / "missing-token.json"
    monkeypatch.setattr(settings, "SCHWAB_API_KEY", "test-key")
    monkeypatch.setattr(settings, "SCHWAB_APP_SECRET", "test-secret")
    monkeypatch.setattr(settings, "SCHWAB_CALLBACK_URL", "https://127.0.0.1:8182")
    monkeypatch.setattr(settings, "SCHWAB_TOKEN_PATH", str(missing))

    provider = SchwabProvider()

    with pytest.raises(ProviderConnectionError) as exc:
        await provider._get_client()

    assert "token_path" in exc.value.details
    assert exc.value.details["token_path"] == str(missing)


def test_decimal_conversion_from_float(provider: SchwabProvider):
    bars = provider._parse_ohlcv(
        {
            "candles": [
                {
                    "datetime": 1715731200000,
                    "open": 182.6,
                    "high": 183.2,
                    "low": 181.8,
                    "close": 182.63,
                    "volume": 100,
                }
            ]
        },
        "AAPL",
    )

    assert bars[0].close == Decimal("182.63")


@pytest.mark.asyncio
async def test_missing_token_file_from_easy_client_raises_connection_error(
    monkeypatch,
    tmp_path: Path,
):
    token_file = tmp_path / "token.json"
    token_file.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(settings, "SCHWAB_API_KEY", "test-key")
    monkeypatch.setattr(settings, "SCHWAB_APP_SECRET", "test-secret")
    monkeypatch.setattr(settings, "SCHWAB_CALLBACK_URL", "https://127.0.0.1:8182")
    monkeypatch.setattr(settings, "SCHWAB_TOKEN_PATH", str(token_file))

    provider = SchwabProvider()

    with patch("app.providers.schwab.easy_client", side_effect=FileNotFoundError("missing token")):
        with pytest.raises(ProviderConnectionError):
            await provider._get_client()
