"""Polygon mapping for index symbols and entitlement detection."""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.providers.polygon import PolygonProvider
from app.utils.errors import DataNotFoundError, ProviderError, ProviderNotEntitledError


def response(status: int, body: dict | None = None, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body if body is not None else {}
    resp.text = text
    return resp


@pytest.fixture
def provider():
    with patch("app.providers.polygon.httpx.AsyncClient") as client:
        client.return_value.get = AsyncMock()
        instance = PolygonProvider()
        instance.api_key = "key"
        yield instance


def calls(provider) -> list[str]:
    return [call.args[0] for call in provider._client.get.call_args_list]


START = datetime(2026, 11, 1, tzinfo=UTC)
END = datetime(2026, 11, 6, tzinfo=UTC)


def test_declared_support():
    support = {"stock", "etf", "index"}
    assert PolygonProvider.price_sec_types == support
    assert PolygonProvider.price_history_sec_types == support
    assert PolygonProvider.option_underlying_sec_types == support
    assert "future" not in PolygonProvider.price_sec_types


def test_format_ticker_index(provider):
    assert provider._format_ticker("SPX", "index") == "I:SPX"
    assert provider._format_ticker("I:SPX", "index") == "I:SPX"
    assert provider._format_ticker("SPY", "etf") == "SPY"


async def test_index_last_price_uses_snapshot(provider):
    provider._client.get.return_value = response(
        200,
        {
            "results": [
                {
                    "ticker": "I:SPX",
                    "value": 5123.4,
                    "last_updated": 1_762_300_800_000_000_000,
                }
            ]
        },
    )
    quote = await provider.get_last_price("SPX", sec_type="index")
    assert calls(provider) == ["/v3/snapshot/indices"]
    params = provider._client.get.call_args.kwargs["params"]
    assert params["ticker.any_of"] == "I:SPX"
    assert quote.price == Decimal("5123.4")
    assert quote.symbol == "SPX"
    assert quote.source_instrument == "I:SPX"


async def test_index_last_price_falls_back_to_previous_close(provider):
    provider._client.get.side_effect = [
        response(403, {"status": "NOT_AUTHORIZED"}),
        response(200, {"results": [{"c": 5000, "t": 1_762_300_800_000}]}),
    ]
    quote = await provider.get_last_price("SPX", sec_type="index")
    assert calls(provider) == [
        "/v3/snapshot/indices",
        "/v2/aggs/ticker/I:SPX/prev",
    ]
    assert quote.price == Decimal(5000)
    assert quote.source_instrument == "I:SPX"
    assert "delayed/prev" in quote.provider


async def test_index_snapshot_entry_error_falls_back(provider):
    provider._client.get.side_effect = [
        response(
            200,
            {"results": [{"ticker": "I:SPX", "error": "NOT_ENTITLED"}]},
        ),
        response(200, {"results": [{"c": 5000, "t": 1_762_300_800_000}]}),
    ]
    quote = await provider.get_last_price("SPX", sec_type="index")
    assert quote.price == Decimal(5000)


async def test_index_without_any_access_is_not_entitled(provider):
    provider._client.get.side_effect = [
        response(403, {"status": "NOT_AUTHORIZED"}),
        response(
            403, {"status": "NOT_AUTHORIZED", "message": "Not entitled to this data."}
        ),
    ]
    with pytest.raises(ProviderNotEntitledError) as error:
        await provider.get_last_price("SPX", sec_type="index")
    assert error.value.code == "PROVIDER_NOT_ENTITLED"
    assert error.value.details["symbol"] == "I:SPX"
    assert error.value.details["instrument"] == "I:SPX"
    assert error.value.details["provider_message"] == "Not entitled to this data."


async def test_stock_fallback_403_is_not_entitled(provider):
    provider._client.get.side_effect = [
        response(403),
        response(403, {"status": "NOT_AUTHORIZED", "message": "Upgrade your plan"}),
    ]
    with pytest.raises(ProviderNotEntitledError) as error:
        await provider.get_last_price("AAPL")
    assert error.value.details["symbol"] == "AAPL"
    assert error.value.details["provider_message"] == "Upgrade your plan"


async def test_unknown_index_returns_not_found(provider):
    provider._client.get.return_value = response(200, {"results": []})
    with pytest.raises(DataNotFoundError):
        await provider.get_last_price("NOPE", sec_type="index")


async def test_invalid_key_is_not_an_entitlement_error(provider):
    resp = response(401, {"status": "ERROR"})
    resp.raise_for_status.side_effect = RuntimeError("401 Unauthorized")
    provider._client.get.return_value = resp
    with pytest.raises(ProviderError) as error:
        await provider.get_last_price("SPX", sec_type="index")
    assert not isinstance(error.value, ProviderNotEntitledError)


async def test_index_history_uses_i_ticker(provider):
    provider._client.get.return_value = response(
        200,
        {
            "results": [
                {"o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10, "t": 1_762_300_800_000}
            ]
        },
    )
    bars = await provider.get_historical_prices(
        "SPX", "1d", START, END, sec_type="index"
    )
    assert calls(provider)[0].startswith("/v2/aggs/ticker/I:SPX/range/1/day/")
    assert [bar.source_instrument for bar in bars] == ["I:SPX"]
    assert bars[0].symbol == "SPX"


async def test_stock_history_has_no_source_instrument(provider):
    provider._client.get.return_value = response(
        200,
        {"results": [{"o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10, "t": 1_762_300_800_000}]},
    )
    bars = await provider.get_historical_prices("AAPL", "1d", START, END)
    assert bars[0].source_instrument is None


async def test_history_403_is_not_entitled(provider):
    provider._client.get.return_value = response(
        403, {"status": "NOT_AUTHORIZED", "message": "plan"}
    )
    with pytest.raises(ProviderNotEntitledError) as error:
        await provider.get_historical_prices("SPX", "1d", START, END, sec_type="index")
    assert error.value.details["symbol"] == "I:SPX"


async def test_not_authorized_body_with_200_is_not_entitled(provider):
    provider._client.get.return_value = response(
        200, {"status": "NOT_AUTHORIZED", "message": "nope"}
    )
    with pytest.raises(ProviderNotEntitledError):
        await provider.get_historical_prices("AAPL", "1d", START, END)


async def test_index_option_chain_uses_i_underlying(provider):
    provider._client.get.return_value = response(200, {"results": []})
    chain = await provider.get_option_chain(
        "SPX", date(2026, 11, 20), sec_type="index"
    )
    assert calls(provider) == ["/v3/snapshot/options/I:SPX"]
    assert chain.underlying_symbol == "SPX"


async def test_option_chain_403_is_not_entitled(provider):
    provider._client.get.return_value = response(403, text="forbidden")
    with pytest.raises(ProviderNotEntitledError) as error:
        await provider.get_option_chain("AAPL", date(2026, 11, 20))
    assert error.value.details["symbol"] == "AAPL"
    assert error.value.details["instrument"] == "AAPL"


async def test_option_quote_403_is_not_entitled(provider):
    provider._client.get.return_value = response(403)
    with pytest.raises(ProviderNotEntitledError):
        await provider.get_option_quote(
            "SPX", "SPX261120C05000000", sec_type="index"
        )
    assert calls(provider) == ["/v3/snapshot/options/I:SPX/O:SPX261120C05000000"]
