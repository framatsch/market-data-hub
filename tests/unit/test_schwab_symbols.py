"""Schwab mapping for index/future symbols and 403 classification."""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, Mock

import pytest

from app.config import settings
from app.providers.schwab import SchwabProvider, _is_entitlement_body, _native_symbol
from app.utils.errors import (
    DataNotFoundError,
    ProviderConnectionError,
    ProviderNotEntitledError,
)


class _Response:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


def quote_payload(key: str) -> dict:
    return {key: {"quote": {"lastPrice": 5000.5, "totalVolume": 10}}}


def candles_payload() -> dict:
    return {
        "candles": [
            {
                "datetime": 1_762_300_800_000,
                "open": 1,
                "high": 2,
                "low": 0.5,
                "close": 1.5,
                "volume": 7,
            }
        ]
    }


@pytest.fixture
def provider(monkeypatch) -> SchwabProvider:
    monkeypatch.setattr(settings, "SCHWAB_RATE_LIMIT_PER_SEC", 50)
    monkeypatch.setattr(settings, "SCHWAB_TIMEOUT_SECONDS", 10)
    instance = SchwabProvider()
    instance._client = Mock()
    instance._get_client = AsyncMock(side_effect=lambda: instance._client)
    return instance


def test_declared_support():
    assert SchwabProvider.price_sec_types == {"stock", "etf", "index", "future"}
    assert SchwabProvider.price_history_sec_types == {"stock", "etf", "index"}
    assert SchwabProvider.option_underlying_sec_types == {"stock", "etf", "index"}


@pytest.mark.parametrize(
    "root,sec_type,expected",
    [
        ("SPX", "index", "$SPX"),
        ("OEX", "index", "$OEX"),
        ("ES", "future", "/ES"),
        ("AAPL", "stock", "AAPL"),
        ("SPY", "etf", "SPY"),
    ],
)
def test_native_symbol(root, sec_type, expected):
    assert _native_symbol(root, sec_type) == expected


async def test_index_last_price_queries_dollar_symbol(provider):
    provider._client.get_quotes = AsyncMock(
        return_value=_Response(200, quote_payload("$SPX"))
    )
    quote = await provider.get_last_price("SPX", sec_type="index")
    provider._client.get_quotes.assert_awaited_once_with(["$SPX"])
    assert quote.symbol == "SPX"
    assert quote.source_instrument == "$SPX"


async def test_future_last_price_queries_slash_symbol(provider):
    provider._client.get_quotes = AsyncMock(
        return_value=_Response(200, quote_payload("/ES"))
    )
    quote = await provider.get_last_price("ES", sec_type="future")
    provider._client.get_quotes.assert_awaited_once_with(["/ES"])
    assert quote.source_instrument == "/ES"


def future_quote(contract, product, *, active=True):
    # Schwab resolves /ES to its active contract and keys the response by /ESZ26.
    return {
        "assetMainType": "FUTURE",
        "symbol": contract,
        "quote": {"lastPrice": 7568.0, "totalVolume": 1179412},
        "reference": {"product": product, "futureIsActive": active},
    }


async def test_future_quote_resolves_active_contract_response(provider):
    provider._client.get_quotes = AsyncMock(return_value=_Response(200, {
        "/NQZ26": future_quote("/NQZ26", "/NQ"),
        "/ESH27": future_quote("/ESH27", "/ES", active=False),
        "/ESZ26": future_quote("/ESZ26", "/ES"),
    }))
    quote = await provider.get_last_price("ES", sec_type="future")
    provider._client.get_quotes.assert_awaited_once_with(["/ES"])
    assert quote.symbol == "ES"
    assert quote.price == 7568
    assert quote.source_instrument == "/ESZ26"


@pytest.mark.parametrize("payload", [
    {"/NQZ26": future_quote("/NQZ26", "/NQ")},
    {"/ESZ26": future_quote("/ESZ26", "/ES", active=False)},
    {"/ESZ26": {"assetMainType": "FUTURE", "quote": {"lastPrice": 7568}}},
    {
        "/ESZ26": future_quote("/ESZ26", "/ES"),
        "/ESH27": future_quote("/ESH27", "/ES"),
    },
])
async def test_future_quote_never_guesses_an_unverified_contract(provider, payload):
    provider._client.get_quotes = AsyncMock(return_value=_Response(200, payload))
    with pytest.raises(DataNotFoundError):
        await provider.get_last_price("ES", sec_type="future")


async def test_stock_quote_has_no_source_instrument(provider):
    provider._client.get_quotes = AsyncMock(
        return_value=_Response(200, quote_payload("AAPL"))
    )
    quote = await provider.get_last_price("AAPL")
    provider._client.get_quotes.assert_awaited_once_with(["AAPL"])
    assert quote.source_instrument is None


async def test_index_history_queries_dollar_symbol(provider):
    history = AsyncMock(return_value=_Response(200, candles_payload()))
    provider._client.get_price_history_every_day = history
    bars = await provider.get_historical_prices(
        "SPX",
        "1d",
        datetime(2026, 11, 1, tzinfo=UTC),
        datetime(2026, 11, 6, tzinfo=UTC),
        sec_type="index",
    )
    assert history.await_args.kwargs["symbol"] == "$SPX"
    assert [bar.source_instrument for bar in bars] == ["$SPX"]


async def test_index_option_chain_queries_dollar_underlying(provider):
    chain = AsyncMock(return_value=_Response(200, {}))
    provider._client.get_option_chain = chain
    result = await provider.get_option_chain(
        "SPX", date(2026, 11, 20), sec_type="index"
    )
    assert chain.await_args.args[0] == "$SPX"
    assert result.underlying_symbol == "SPX"


@pytest.mark.parametrize(
    "body",
    [
        "Not entitled to this market data",
        '{"message": "No subscription for futures quotes"}',
    ],
)
async def test_403_with_entitlement_body_is_not_entitled(provider, body):
    provider._client.get_quotes = AsyncMock(return_value=_Response(403, text=body))
    with pytest.raises(ProviderNotEntitledError) as error:
        await provider.get_last_price("ES", sec_type="future")
    assert error.value.code == "PROVIDER_NOT_ENTITLED"
    assert error.value.details["symbol"] == "F:ES"
    assert error.value.details["instrument"] == "/ES"
    assert error.value.details["provider_message"] == body
    assert provider._client is not None
    assert not provider.is_paused


async def test_entitlement_error_on_option_chain(provider):
    provider._client.get_option_chain = AsyncMock(
        return_value=_Response(403, text="Account is not entitled to index options")
    )
    with pytest.raises(ProviderNotEntitledError) as error:
        await provider.get_option_chain("SPX", date(2026, 11, 20), sec_type="index")
    assert error.value.details["symbol"] == "I:SPX"
    assert error.value.details["instrument"] == "$SPX"


@pytest.mark.parametrize(
    "body",
    ["", "Forbidden", "Access token has expired", "Token not entitled: refresh token"],
)
async def test_403_token_failure_keeps_client_reset(provider, body):
    provider._client.get_quotes = AsyncMock(return_value=_Response(403, text=body))
    provider._fire_webhook = AsyncMock()
    with pytest.raises(ProviderConnectionError):
        await provider.get_last_price("AAPL")
    assert provider._client is None


async def test_401_is_never_an_entitlement_error(provider):
    provider._client.get_quotes = AsyncMock(
        return_value=_Response(401, text="not entitled")
    )
    provider._fire_webhook = AsyncMock()
    with pytest.raises(ProviderConnectionError):
        await provider.get_last_price("AAPL")


@pytest.mark.parametrize(
    "body,expected",
    [
        (None, False),
        ("entitlement missing", True),
        ("subscription required", True),
        ("token expired, no subscription", False),
    ],
)
def test_entitlement_body_classifier(body, expected):
    assert _is_entitlement_body(body) is expected
