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

import time
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.config import settings
from app.providers.base import BaseOptionsProvider
from app.providers.schwab import SchwabProvider
from app.utils.errors import (
    AppError,
    DataNotFoundError,
    DataValidationError,
    ProviderConnectionError,
    ProviderTimeoutError,
)


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
    monkeypatch.setattr(settings, "SCHWAB_TIMEOUT_SECONDS", 10)

    return SchwabProvider()


@pytest.fixture
def option_chain_response() -> dict:
    return {
        "callExpDateMap": {
            "2024-04-05:7": {
                "185.0": [
                    {
                        "symbol": "AAPL  240405C00185000",
                        "strikePrice": 185.0,
                        "bid": 4.1,
                        "ask": 4.3,
                        "last": 4.2,
                        "mark": 4.2,
                        "totalVolume": 120,
                        "openInterest": 800,
                        "volatility": 22.3,
                        "delta": 0.56,
                        "gamma": 0.08,
                        "theta": -0.05,
                        "vega": 0.11,
                    }
                ],
                "190.0": [
                    {
                        "symbol": "AAPL  240405C00190000",
                        "strikePrice": 190.0,
                        "bid": 2.1,
                        "ask": 2.3,
                        "last": 2.2,
                        "mark": 2.2,
                        "totalVolume": 80,
                        "openInterest": 600,
                        "volatility": 20.1,
                        "delta": 0.42,
                        "gamma": 0.07,
                        "theta": -0.04,
                        "vega": 0.10,
                    }
                ],
            }
        },
        "putExpDateMap": {
            "2024-04-05:7": {
                "185.0": [
                    {
                        "symbol": "AAPL  240405P00185000",
                        "strikePrice": 185.0,
                        "bid": 3.8,
                        "ask": 4.0,
                        "last": 3.9,
                        "mark": 3.9,
                        "totalVolume": 110,
                        "openInterest": 700,
                        "volatility": 23.0,
                        "delta": -0.44,
                        "gamma": 0.09,
                        "theta": -0.06,
                        "vega": 0.12,
                    }
                ],
                "190.0": [
                    {
                        "symbol": "AAPL  240405P00190000",
                        "strikePrice": 190.0,
                        "bid": 5.5,
                        "ask": 5.8,
                        "last": 5.7,
                        "mark": 5.7,
                        "totalVolume": 65,
                        "openInterest": 500,
                        "volatility": 24.1,
                        "delta": -0.58,
                        "gamma": 0.10,
                        "theta": -0.07,
                        "vega": 0.14,
                    }
                ],
            }
        },
    }


# ---------------------------------------------------------------------------
# Happy path — historical prices
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Happy path — last price
# ---------------------------------------------------------------------------

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
    assert quote.bid == Decimal("182.6")
    assert quote.ask == Decimal("182.7")
    assert quote.volume == 12345


@pytest.mark.asyncio
async def test_get_last_price_unknown_symbol(provider: SchwabProvider):
    client = Mock()
    client.get_quotes = AsyncMock(return_value=_Response(200, {"MSFT": {"quote": {"lastPrice": 11.0}}}))
    provider._get_client = AsyncMock(return_value=client)

    with pytest.raises(DataNotFoundError):
        await provider.get_last_price("AAPL")


# ---------------------------------------------------------------------------
# Connection / auth errors
# ---------------------------------------------------------------------------

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

    assert "hint" in exc.value.details


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


@pytest.mark.asyncio
async def test_expired_token_raises_connection_error(monkeypatch, tmp_path: Path):
    """Generic exception from easy_client (e.g. expired token) → ProviderConnectionError with hint."""
    token_file = tmp_path / "token.json"
    token_file.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(settings, "SCHWAB_API_KEY", "test-key")
    monkeypatch.setattr(settings, "SCHWAB_APP_SECRET", "test-secret")
    monkeypatch.setattr(settings, "SCHWAB_CALLBACK_URL", "https://127.0.0.1:8182")
    monkeypatch.setattr(settings, "SCHWAB_TOKEN_PATH", str(token_file))

    provider = SchwabProvider()

    with patch("app.providers.schwab.easy_client", side_effect=Exception("token_expired")):
        with pytest.raises(ProviderConnectionError) as exc:
            await provider._get_client()

    assert "Re-authorize through the admin UI" in exc.value.message


# ---------------------------------------------------------------------------
# HTTP error codes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_last_price_429_raises_timeout(provider: SchwabProvider):
    client = Mock()
    client.get_quotes = AsyncMock(return_value=_Response(429, {}))
    provider._get_client = AsyncMock(return_value=client)

    with pytest.raises(ProviderTimeoutError):
        await provider.get_last_price("AAPL")


@pytest.mark.asyncio
async def test_get_historical_prices_429_raises_timeout(provider: SchwabProvider):
    client = Mock()
    client.get_price_history_every_day = AsyncMock(return_value=_Response(429, {}))
    provider._get_client = AsyncMock(return_value=client)

    with pytest.raises(ProviderTimeoutError):
        await provider.get_historical_prices(
            "AAPL", "1d",
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 1, 31, tzinfo=timezone.utc),
        )


@pytest.mark.asyncio
async def test_get_last_price_401_clears_client_and_raises_connection_error(provider: SchwabProvider):
    """401 from Schwab API → clears cached client + raises ProviderConnectionError."""
    client = Mock()
    client.get_quotes = AsyncMock(return_value=_Response(401, {}))
    provider._get_client = AsyncMock(return_value=client)
    provider._client = client  # simulate cached client

    with pytest.raises(ProviderConnectionError) as exc:
        await provider.get_last_price("AAPL")

    assert "expired" in exc.value.message.lower() or "invalid" in exc.value.message.lower()
    assert provider._client is None  # must be cleared so next call re-authenticates
    assert provider._paused is True


@pytest.mark.asyncio
async def test_get_last_price_403_clears_client_and_raises_connection_error(provider: SchwabProvider):
    client = Mock()
    client.get_quotes = AsyncMock(return_value=_Response(403, {}))
    provider._get_client = AsyncMock(return_value=client)
    provider._client = client

    with pytest.raises(ProviderConnectionError):
        await provider.get_last_price("AAPL")

    assert provider._client is None
    assert provider._paused is True


@pytest.mark.asyncio
async def test_test_connection_success(provider: SchwabProvider):
    client = Mock()
    client.get_accounts = AsyncMock(return_value=_Response(200, {}))
    provider._get_client = AsyncMock(return_value=client)

    result = await provider.test_connection()

    assert result["status_code"] == 200
    assert result["success"] is True
    assert result["message"] == "Schwab OAuth token valid"


@pytest.mark.asyncio
async def test_test_connection_auth_failure(provider: SchwabProvider):
    client = Mock()
    client.get_accounts = AsyncMock(return_value=_Response(401, {}))
    provider._get_client = AsyncMock(return_value=client)

    result = await provider.test_connection()

    assert result["status_code"] == 401
    assert result["success"] is False
    assert result["message"] == "Schwab OAuth token expired or invalid"


@pytest.mark.asyncio
async def test_test_connection_service_unavailable(provider: SchwabProvider):
    provider._get_client = AsyncMock(side_effect=Exception("down"))

    result = await provider.test_connection()

    assert result["status_code"] == 503
    assert result["success"] is False
    assert result["message"] == "Schwab service unavailable"


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rate_limit_exceeded_raises_timeout(monkeypatch, tmp_path: Path):
    """In-process rate limit: fill the window, next call should raise ProviderTimeoutError."""
    token_file = tmp_path / "token.json"
    token_file.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(settings, "SCHWAB_API_KEY", "test-key")
    monkeypatch.setattr(settings, "SCHWAB_APP_SECRET", "test-secret")
    monkeypatch.setattr(settings, "SCHWAB_CALLBACK_URL", "https://127.0.0.1:8182")
    monkeypatch.setattr(settings, "SCHWAB_TOKEN_PATH", str(token_file))
    monkeypatch.setattr(settings, "SCHWAB_RATE_LIMIT_PER_SEC", 3)

    provider = SchwabProvider()
    # Pre-fill the window with `limit` timestamps right now
    now = time.time()
    for _ in range(3):
        provider._request_times.append(now)

    with pytest.raises(ProviderTimeoutError) as exc:
        await provider._check_rate_limit()

    assert exc.value.details["reason"] == "rate limit exceeded"


@pytest.mark.asyncio
async def test_rate_limit_window_expires_allows_new_requests(monkeypatch, tmp_path: Path):
    """After the 1-second window expires, requests should be allowed again."""
    token_file = tmp_path / "token.json"
    token_file.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(settings, "SCHWAB_API_KEY", "test-key")
    monkeypatch.setattr(settings, "SCHWAB_APP_SECRET", "test-secret")
    monkeypatch.setattr(settings, "SCHWAB_CALLBACK_URL", "https://127.0.0.1:8182")
    monkeypatch.setattr(settings, "SCHWAB_TOKEN_PATH", str(token_file))
    monkeypatch.setattr(settings, "SCHWAB_RATE_LIMIT_PER_SEC", 2)

    provider = SchwabProvider()
    # Fill with timestamps 2 seconds ago (outside the 1s window)
    old_time = time.time() - 2.0
    provider._request_times.append(old_time)
    provider._request_times.append(old_time)

    # Should NOT raise — old entries are evicted
    await provider._check_rate_limit()


# ---------------------------------------------------------------------------
# close() lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_close_sets_client_to_none(provider: SchwabProvider):
    mock_client = Mock()
    mock_client.close = AsyncMock()
    provider._client = mock_client

    await provider.close()

    assert provider._client is None
    mock_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_noop_when_no_client(provider: SchwabProvider):
    provider._client = None
    await provider.close()  # must not raise
    assert provider._client is None


@pytest.mark.asyncio
async def test_close_sync_close_method(provider: SchwabProvider):
    """close() handles sync (non-coroutine) close method gracefully."""
    mock_client = Mock()
    mock_client.close = Mock(return_value=None)  # sync, not coroutine
    provider._client = mock_client

    await provider.close()

    assert provider._client is None


@pytest.mark.asyncio
async def test_close_removes_temp_token_file(provider: SchwabProvider, tmp_path: Path):
    temp_token = tmp_path / "repo-token.json"
    temp_token.write_text('{"access_token": "token"}', encoding="utf-8")
    provider._temp_token_path = str(temp_token)
    provider._client = None

    await provider.close()

    assert provider._temp_token_path is None
    assert not temp_token.exists()


# ---------------------------------------------------------------------------
# Decimal conversion
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
def test_decimal_conversion_uses_str_path(provider: SchwabProvider, field: str):
    """All OHLCV fields use Decimal(str(value)), not Decimal(float) — precision preserved."""
    candle_values = {"open": 182.6, "high": 183.2, "low": 181.8, "close": 182.63}
    bars = provider._parse_ohlcv(
        {
            "candles": [
                {
                    "datetime": 1715731200000,
                    **candle_values,
                    "volume": 100,
                }
            ]
        },
        "AAPL",
    )

    result = getattr(bars[0], field)
    expected = Decimal(str(candle_values[field]))
    float_result = Decimal(candle_values[field])  # the buggy form

    assert result == expected
    # Prove the two forms differ for floats that lose precision
    if expected != float_result:
        assert result != float_result, f"{field}: should use str-path, not direct float Decimal"


# ---------------------------------------------------------------------------
# Options support
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_option_chain_success(provider: SchwabProvider, option_chain_response: dict):
    client = Mock()
    client.get_option_chain = Mock(return_value=_Response(200, option_chain_response))
    provider._get_client = AsyncMock(return_value=client)

    chain = await provider.get_option_chain("AAPL", date(2024, 4, 5))

    assert chain.provider == "schwab"
    assert len(chain.options) == 4
    assert chain.options[0].strike == Decimal("185.0")


@pytest.mark.asyncio
async def test_get_option_chain_min_strike_filter(provider: SchwabProvider, option_chain_response: dict):
    client = Mock()
    client.get_option_chain = Mock(return_value=_Response(200, option_chain_response))
    provider._get_client = AsyncMock(return_value=client)

    chain = await provider.get_option_chain("AAPL", date(2024, 4, 5), min_strike=Decimal("187.0"))

    assert len(chain.options) == 2
    assert {option.strike for option in chain.options} == {Decimal("190.0")}


@pytest.mark.asyncio
async def test_get_option_chain_right_filter_call(provider: SchwabProvider, option_chain_response: dict):
    client = Mock()
    client.get_option_chain = Mock(return_value=_Response(200, option_chain_response))
    provider._get_client = AsyncMock(return_value=client)

    chain = await provider.get_option_chain("AAPL", date(2024, 4, 5), right="call")

    assert len(chain.options) == 2
    assert all(option.type == "call" for option in chain.options)


@pytest.mark.asyncio
async def test_get_option_chain_uses_volatility_for_iv(provider: SchwabProvider, option_chain_response: dict):
    option_chain_response["callExpDateMap"]["2024-04-05:7"]["185.0"][0]["volatility"] = 22.345
    client = Mock()
    client.get_option_chain = Mock(return_value=_Response(200, option_chain_response))
    provider._get_client = AsyncMock(return_value=client)

    chain = await provider.get_option_chain("AAPL", date(2024, 4, 5), right="call")

    assert chain.options[0].implied_volatility == 22.345


@pytest.mark.asyncio
async def test_get_option_chain_last_zero_falls_back_to_mark(provider: SchwabProvider, option_chain_response: dict):
    option_chain_response["callExpDateMap"]["2024-04-05:7"]["185.0"][0]["last"] = 0
    option_chain_response["callExpDateMap"]["2024-04-05:7"]["185.0"][0]["mark"] = 4.45
    client = Mock()
    client.get_option_chain = Mock(return_value=_Response(200, option_chain_response))
    provider._get_client = AsyncMock(return_value=client)

    chain = await provider.get_option_chain("AAPL", date(2024, 4, 5), right="call")

    assert chain.options[0].price == Decimal("4.45")


@pytest.mark.asyncio
async def test_get_option_chain_429_raises_timeout(provider: SchwabProvider):
    client = Mock()
    client.get_option_chain = Mock(return_value=_Response(429, {}))
    provider._get_client = AsyncMock(return_value=client)

    with pytest.raises(ProviderTimeoutError) as exc:
        await provider.get_option_chain("AAPL", date(2024, 4, 5))

    assert exc.value.details["status_code"] == 429


@pytest.mark.asyncio
async def test_get_option_quote_success(provider: SchwabProvider):
    client = Mock()
    client.get_quotes = Mock(
        return_value=_Response(
            200,
            {
                "AAPL  240405C00185000": {
                    "quote": {
                        "strikePrice": 185.0,
                        "bidPrice": 4.1,
                        "askPrice": 4.3,
                        "lastPrice": 4.2,
                        "totalVolume": 120,
                        "openInterest": 800,
                        "volatility": 22.3,
                        "delta": 0.56,
                        "gamma": 0.08,
                        "theta": -0.05,
                        "vega": 0.11,
                    }
                }
            },
        )
    )
    provider._get_client = AsyncMock(return_value=client)

    quote = await provider.get_option_quote("AAPL", "AAPL  240405C00185000")

    assert quote.provider == "schwab"
    assert quote.symbol == "AAPL  240405C00185000"
    assert quote.type == "call"
    assert quote.strike == Decimal("185.0")


@pytest.mark.asyncio
async def test_get_option_quote_invalid_occ_symbol(provider: SchwabProvider):
    client = Mock()
    client.get_quotes = Mock(return_value=_Response(200, {"bad-occ": {"quote": {}}}))
    provider._get_client = AsyncMock(return_value=client)

    with pytest.raises(AppError) as exc:
        await provider.get_option_quote("AAPL", "bad-occ")

    assert exc.value.code == "INVALID_PROVIDER"
    assert exc.value.details.get("status_code") == 400


def test_schwab_provider_is_options_provider(provider: SchwabProvider):
    assert isinstance(provider, BaseOptionsProvider)
