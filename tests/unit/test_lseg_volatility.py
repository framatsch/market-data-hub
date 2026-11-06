import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

from app.providers import lseg
from app.providers.base import BaseVolatilityProvider
from app.providers.lseg import LSEGProvider, _volatility_instrument
from app.utils.errors import (
    DataNotFoundError,
    DataValidationError,
    ProviderConnectionError,
    ProviderError,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "lseg_volatility"


@pytest.fixture
def provider(monkeypatch):
    provider = LSEGProvider()
    monkeypatch.setattr(provider, "_get_session", Mock())
    monkeypatch.setattr(provider, "_throttle", Mock())
    monkeypatch.setattr(lseg.time, "sleep", Mock())
    monkeypatch.setattr(provider, "_ticker_to_ric", Mock(side_effect=AssertionError("No search")))
    return provider


def snapshot_frame(instrument, filename=None):
    metadata = pd.read_csv(FIXTURES / "R6_underlying_check.csv")
    metadata = metadata[metadata.Instrument == instrument]
    if filename is None:
        return metadata.reset_index(drop=True)
    frame = pd.read_csv(FIXTURES / filename).drop(columns=["Unnamed: 0"], errors="ignore")
    if metadata.empty:
        # Synthetic metadata only; the recorded snapshot IV/date remain unchanged.
        frame["GN_TXT16_5"] = "OPRA"
        frame["UNDERLYING"] = instrument.removesuffix("ATMIV.U")
        frame["INST_DESC"] = "APPLE INC" if instrument.startswith("AAPL") else "SPDR S&P 500 ETF"
    else:
        for field in lseg.META_FIDS:
            frame[field] = metadata.iloc[0].get(field)
    return frame


@pytest.mark.parametrize("symbol,sec_type,ric,expected", [
    ("aapl", "stock", None, "AAPLATMIV.U"),
    ("spy", "etf", None, "SPYATMIV.U"),
    ("^SPX", "index", None, "SPXATMIV.U"),
    (".NDX", "index", None, "NDXATMIV.U"),
    ("es", "future", None, "ESATMIV"),
    ("DAX", "index", "GDAXATMIV.EX", "GDAXATMIV.EX"),
])
def test_instrument_resolution(symbol, sec_type, ric, expected):
    assert _volatility_instrument(symbol, sec_type, ric) == expected


@pytest.mark.parametrize("symbol,sec_type,instrument,filename,iv", [
    ("AAPL", "stock", "AAPLATMIV.U", "P0_full_dump__AAPLATMIV.U.csv", "0.2676"),
    ("SPY", "etf", "SPYATMIV.U", "P0_full_dump__SPYATMIV.U.csv", "0.2173"),
    ("SPX", "index", "SPXATMIV.U", "P1_iv_fids__SPXATMIV.U.csv", "0.1771"),
    ("ES", "future", "ESATMIV", "P1_iv_fids__ESATMIV.csv", "0.1316"),
])
async def test_snapshot(provider, monkeypatch, symbol, sec_type, instrument, filename, iv):
    frame = snapshot_frame(instrument, filename)
    frame["GN_TXT16_5"] = frame["GN_TXT16_5"].map(lambda value: f" {value.lower()} ")
    upstream = Mock(return_value=frame)
    monkeypatch.setattr(lseg.rd, "get_data", upstream)
    result = await provider.get_implied_volatility(symbol.lower(), sec_type)
    assert isinstance(provider, BaseVolatilityProvider)
    assert result.symbol == symbol
    assert result.source_instrument == instrument
    assert result.method == "provider_atm_index"
    assert result.implied[0].iv == Decimal(iv)
    assert [tenor.tenor_days for tenor in result.implied] == [30, 60, 90]
    assert result.as_of == date(2026, 11, 5 if sec_type != "index" else 6)
    assert result.market in {"OPRA", "COMFUT"}
    upstream.assert_called_once_with(instrument, lseg.IV_FIDS + lseg.META_FIDS)
    provider._get_session.assert_called_once()
    provider._throttle.assert_called_once()


async def test_explicit_eurex_override(provider, monkeypatch):
    monkeypatch.setattr(lseg.rd, "get_data", Mock(return_value=snapshot_frame("GDAXATMIV.EX")))
    result = await provider.get_implied_volatility("DAX", ric="GDAXATMIV.EX")
    assert result.market == "EUREX"
    assert result.underlying == ".GDAXI"
    assert result.underlying_name == "OPT DAX INDEX"
    assert result.implied[0].iv == Decimal("0.1829")
    assert result.implied[1].iv is None


async def test_no_provider_cache(provider, monkeypatch):
    upstream = Mock(return_value=snapshot_frame("ESATMIV"))
    monkeypatch.setattr(lseg.rd, "get_data", upstream)
    await provider.get_implied_volatility("ES", "future")
    await provider.get_implied_volatility("ES", "future")
    assert upstream.call_count == 2


async def test_market_mismatch(provider, monkeypatch):
    monkeypatch.setattr(lseg.rd, "get_data", Mock(return_value=snapshot_frame("ESATMIV.U")))
    with pytest.raises(DataValidationError) as error:
        await provider.get_implied_volatility("ES", "future")
    assert error.value.details == {
        "expected_market": ["COMFUT", "CMEG"], "market": "OPRA",
        "underlying_name": "EVERSOURCE ENERG",
    }


@pytest.mark.parametrize("frame", [None, pd.DataFrame(), pd.read_csv(
    FIXTURES / "P1b_batch_mixed__AAPLATMIV.U_MSFTATMIV.U_ZZZZATMIV.U.csv"
).iloc[[2]]])
async def test_missing_snapshot(provider, monkeypatch, frame):
    monkeypatch.setattr(lseg.rd, "get_data", Mock(return_value=frame))
    with pytest.raises(DataNotFoundError) as error:
        await provider.get_implied_volatility("ZZZZ")
    assert error.value.details["reason"] == "no_iv_data"


@pytest.mark.parametrize("operation", ["snapshot", "history"])
@pytest.mark.parametrize("error_row", json.loads((FIXTURES / "errors.json").read_text()))
async def test_entitlement_mapping(provider, monkeypatch, operation, error_row):
    upstream = Mock(side_effect=RuntimeError(error_row["message"]))
    monkeypatch.setattr(lseg.rd, "get_data", upstream)
    with pytest.raises(ProviderError) as error:
        if operation == "snapshot":
            await provider.get_implied_volatility("AAPL")
        else:
            await provider.get_implied_volatility_history("AAPL", date(2026, 1, 1), date(2026, 11, 5))
    assert error.value.code == "PROVIDER_NOT_AVAILABLE"
    assert error.value.details == {"reason": "not_entitled", "instrument": "AAPLATMIV.U"}
    assert upstream.call_count == 1


async def test_transient_error_retries(provider, monkeypatch):
    upstream = Mock(side_effect=TimeoutError("connection timeout"))
    monkeypatch.setattr(lseg.rd, "get_data", upstream)
    with pytest.raises(ProviderConnectionError):
        await provider.get_implied_volatility("AAPL")
    assert upstream.call_count == 3


async def test_daily_history(provider, monkeypatch):
    frame = pd.read_csv(FIXTURES / "P2b_hist_daily_fields__AAPLATMIV.U.csv", index_col="Date")
    frame = frame.astype("Float64").iloc[::-1]
    frame.loc["2026-10-25"] = pd.NA
    frame.loc["2026-10-24"] = [20, pd.NA, 21, pd.NA, 22, pd.NA]
    monkeypatch.setattr(lseg.rd, "get_data", Mock(return_value=snapshot_frame("ESATMIV")))
    definition = Mock()
    definition.return_value.get_data.return_value = SimpleNamespace(data=SimpleNamespace(df=frame))
    monkeypatch.setattr(lseg.historical_pricing.summaries, "Definition", definition)
    result = await provider.get_implied_volatility_history("ES", date(2026, 10, 24), date(2026, 11, 5), sec_type="future")
    assert len(result.points) == 10
    assert result.points[0].date == date(2026, 10, 24)
    assert result.points[0].iv == Decimal("0.2000")
    assert result.points[0].iv_put is None
    assert result.points[-1].iv == Decimal("0.2676")
    assert [point.date for point in result.points] == sorted(point.date for point in result.points)
    definition.assert_called_once_with(
        universe="ESATMIV", interval=lseg.historical_pricing.Intervals.DAILY,
        start="2026-10-23", end="2026-11-05", fields=["30D_A_IM_C", "30D_A_IM_P"],
    )


@pytest.mark.parametrize("frame", [None, pd.DataFrame(), pd.DataFrame({"30D_A_IM_C": [float("nan")], "30D_A_IM_P": [pd.NA]}, index=["2026-11-05"])])
async def test_empty_history(provider, monkeypatch, frame):
    definition = Mock()
    definition.return_value.get_data.return_value = SimpleNamespace(data=SimpleNamespace(df=frame))
    monkeypatch.setattr(lseg.historical_pricing.summaries, "Definition", definition)
    with pytest.raises(DataNotFoundError) as error:
        await provider.get_implied_volatility_history("DAX", date(2026, 1, 1), date(2026, 11, 5), ric="GDAXATMIV.EX")
    assert error.value.details["reason"] == "no_iv_history"


async def test_history_market_validation(provider, monkeypatch):
    monkeypatch.setattr(lseg.rd, "get_data", Mock(return_value=snapshot_frame("ESATMIV.U")))
    definition = Mock()
    monkeypatch.setattr(lseg.historical_pricing.summaries, "Definition", definition)
    with pytest.raises(DataValidationError):
        await provider.get_implied_volatility_history("ES", date(2026, 1, 1), date(2026, 11, 5), sec_type="future")
    definition.assert_not_called()


@pytest.mark.parametrize("message,expected", [("No data to return", DataNotFoundError), ("invalid ric", DataNotFoundError), ("unexpected schema", ProviderError)])
async def test_other_upstream_errors(provider, monkeypatch, message, expected):
    monkeypatch.setattr(lseg.rd, "get_data", Mock(side_effect=RuntimeError(message)))
    with pytest.raises(expected):
        await provider.get_implied_volatility("AAPL")


async def test_invalid_parameters(provider):
    with pytest.raises(DataValidationError):
        await provider.get_implied_volatility_history("AAPL", date(2026, 11, 5), date(2026, 1, 1))
    with pytest.raises(DataValidationError):
        await provider.get_implied_volatility_history("AAPL", date(2026, 1, 1), date(2026, 11, 5), tenor_days=45)
    with pytest.raises(DataValidationError):
        await provider.get_implied_volatility("AAPL", sec_type="option")


@pytest.mark.parametrize("message,expected,reason", [
    ("UserNotPermission: User has no permission", ProviderError, "not_entitled"),
    ("No data to return", DataNotFoundError, "no_iv_history"),
    ("503 connection timeout", ProviderConnectionError, None),
])
async def test_history_upstream_error_mapping(provider, monkeypatch, message, expected, reason):
    definition = Mock()
    definition.return_value.get_data.side_effect = RuntimeError(message)
    monkeypatch.setattr(lseg.historical_pricing.summaries, "Definition", definition)
    with pytest.raises(expected) as error:
        await provider.get_implied_volatility_history(
            "DAX", date(2026, 1, 1), date(2026, 11, 5), ric="GDAXATMIV.EX"
        )
    if reason:
        assert error.value.details["reason"] == reason
    assert definition.call_count == (3 if expected is ProviderConnectionError else 1)


@pytest.mark.parametrize("frame", [None, pd.DataFrame(), pd.DataFrame({"GN_TXT16_5": [pd.NA]})])
async def test_missing_history_metadata(provider, monkeypatch, frame):
    monkeypatch.setattr(lseg.rd, "get_data", Mock(return_value=frame))
    with pytest.raises(DataNotFoundError) as error:
        await provider.get_implied_volatility_history("ZZZZ", date(2026, 1, 1), date(2026, 11, 5))
    assert error.value.details["reason"] == "no_iv_history"


def test_entitlement_text_is_not_retryable_even_with_503(provider):
    assert not provider._is_retryable_error(RuntimeError("503 insufficient scope"))
    assert not provider._is_retryable_error(RuntimeError("503 user has no permission"))


@pytest.mark.parametrize("start,end,expected_dates", [
    (date(2026, 11, 5), date(2026, 11, 5), [date(2026, 11, 5)]),
    (date(2026, 11, 4), date(2026, 11, 5), [date(2026, 11, 4), date(2026, 11, 5)]),
])
async def test_history_includes_start_date_with_exclusive_upstream(
    provider, monkeypatch, start, end, expected_dates
):
    frame = pd.read_csv(
        FIXTURES / "P2b_hist_daily_fields__AAPLATMIV.U.csv", index_col="Date"
    )

    def upstream_definition(**kwargs):
        # Live LSEG daily summaries omit the row at an exact start-date boundary.
        selected = frame.loc[(frame.index > kwargs["start"]) & (frame.index <= kwargs["end"])]
        response = SimpleNamespace(data=SimpleNamespace(df=selected))
        return SimpleNamespace(get_data=lambda: response)

    definition = Mock(side_effect=upstream_definition)
    monkeypatch.setattr(lseg.historical_pricing.summaries, "Definition", definition)
    result = await provider.get_implied_volatility_history(
        "AAPL", start, end, ric="AAPLATMIV.U"
    )
    assert [point.date for point in result.points] == expected_dates
    assert result.points[-1].iv == Decimal("0.2676")
