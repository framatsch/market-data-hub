"""LSEG price mapping for index/future symbols and entitlement detection."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

from app.providers import lseg
from app.providers.lseg import LSEGProvider, _native_instrument
from app.utils.errors import ProviderNotEntitledError


@pytest.fixture
def provider(monkeypatch):
    provider = LSEGProvider()
    monkeypatch.setattr(provider, "_get_session", Mock())
    monkeypatch.setattr(provider, "_throttle", Mock())
    monkeypatch.setattr(lseg.time, "sleep", Mock())
    monkeypatch.setattr(
        provider, "_ticker_to_ric", Mock(return_value="AAPL.O")
    )
    return provider


def frame() -> pd.DataFrame:
    index = pd.to_datetime(["2026-11-05"])
    return pd.DataFrame(
        {
            "OPEN_PRC": [1.0],
            "HIGH_1": [3.0],
            "LOW_1": [0.5],
            "TRDPRC_1": [2.0],
            "ACVOL_UNS": [10],
        },
        index=index,
    )


def patch_pricing(monkeypatch, result=None, error=None):
    definition = Mock()
    if error is not None:
        definition.return_value.get_data.side_effect = error
    else:
        definition.return_value.get_data.return_value = SimpleNamespace(
            data=SimpleNamespace(df=result if result is not None else frame())
        )
    monkeypatch.setattr(lseg.historical_pricing.summaries, "Definition", definition)
    return definition


def test_declares_index_and_future_price_support():
    support = {"stock", "etf", "index", "future"}
    assert LSEGProvider.price_sec_types == support
    assert LSEGProvider.price_history_sec_types == support


@pytest.mark.parametrize(
    "root,sec_type,expected",
    [
        ("SPX", "index", ".SPX"),
        ("OEX", "index", ".OEX"),
        ("ES", "future", "ESc1"),
        ("CL", "future", "CLc1"),
        ("ZN", "future", "TYc1"),
        ("ZB", "future", "USc1"),
        ("ZC", "future", "Cc1"),
        ("ZW", "future", "Wc1"),
        ("ZS", "future", "Sc1"),
        ("AAPL", "stock", None),
        ("SPY", "etf", None),
    ],
)
def test_native_instrument(root, sec_type, expected):
    assert _native_instrument(root, sec_type) == expected


async def test_index_history_queries_dot_ric(provider, monkeypatch):
    definition = patch_pricing(monkeypatch)
    bars = await provider.get_historical_prices(
        "SPX",
        "1d",
        datetime(2026, 11, 1, tzinfo=UTC),
        datetime(2026, 11, 6, tzinfo=UTC),
        sec_type="index",
    )
    assert definition.call_args.kwargs["universe"] == ".SPX"
    provider._ticker_to_ric.assert_not_called()
    assert bars[0].source_instrument == ".SPX"


async def test_future_with_deviating_root_history(provider, monkeypatch):
    definition = patch_pricing(monkeypatch)
    bars = await provider.get_historical_prices(
        "ZN",
        "1d",
        datetime(2026, 11, 1, tzinfo=UTC),
        datetime(2026, 11, 6, tzinfo=UTC),
        sec_type="future",
    )
    assert definition.call_args.kwargs["universe"] == "TYc1"
    assert [bar.source_instrument for bar in bars] == ["TYc1"]


async def test_stock_history_uses_ric_search_without_source(provider, monkeypatch):
    definition = patch_pricing(monkeypatch)
    bars = await provider.get_historical_prices(
        "AAPL",
        "1d",
        datetime(2026, 11, 1, tzinfo=UTC),
        datetime(2026, 11, 6, tzinfo=UTC),
    )
    assert definition.call_args.kwargs["universe"] == "AAPL.O"
    assert bars[0].source_instrument is None


async def test_unknown_index_root_passes_through_for_last_price(
    provider, monkeypatch
):
    definition = patch_pricing(monkeypatch)
    quote = await provider.get_last_price("OEX", sec_type="index")
    assert definition.call_args.kwargs["universe"] == ".OEX"
    assert quote.source_instrument == ".OEX"
    provider._ticker_to_ric.assert_not_called()


async def test_last_price_cache_separates_stock_and_future(provider, monkeypatch):
    definition = patch_pricing(monkeypatch)
    await provider.get_last_price("ES", sec_type="future")
    await provider.get_last_price("ES", sec_type="future")
    assert definition.call_count == 1
    await provider.get_last_price("ES")
    assert definition.call_count == 2
    assert definition.call_args.kwargs["universe"] == "AAPL.O"


@pytest.mark.parametrize(
    "message",
    ["UserNotPermission", "User has no permission", "insufficient scope"],
)
async def test_last_price_permission_error_is_not_entitled(
    provider, monkeypatch, message
):
    definition = patch_pricing(monkeypatch, error=RuntimeError(message))
    with pytest.raises(ProviderNotEntitledError) as error:
        await provider.get_last_price("SPX", sec_type="index")
    assert error.value.code == "PROVIDER_NOT_ENTITLED"
    assert error.value.details["symbol"] == "I:SPX"
    assert error.value.details["instrument"] == ".SPX"
    assert error.value.details["provider_message"] == message
    assert definition.return_value.get_data.call_count == 1


async def test_history_permission_error_is_not_entitled(provider, monkeypatch):
    patch_pricing(monkeypatch, error=RuntimeError("UserNotPermission"))
    with pytest.raises(ProviderNotEntitledError) as error:
        await provider.get_historical_prices(
            "ES",
            "1d",
            datetime(2026, 11, 1, tzinfo=UTC),
            datetime(2026, 11, 6, tzinfo=UTC),
            sec_type="future",
        )
    assert error.value.details["symbol"] == "F:ES"
    assert error.value.details["instrument"] == "ESc1"
