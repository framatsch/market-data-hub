import asyncio
import csv
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from eventkit import Event
from ib_async import ContractDetails, Future, Ticker
from ib_async.objects import BarData, BarDataList

from app.config import settings
from app.providers import ibkr
from app.providers.base import BaseVolatilityProvider
from app.providers.ibkr import IBKRProvider
from app.utils.errors import (
    CapabilityNotSupportedError,
    DataNotFoundError,
    DataValidationError,
    ProviderConnectionError,
    ProviderError,
    ProviderTimeoutError,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ibkr_volatility"
LIVE = json.loads((FIXTURES / "report_mdt3_live.json").read_text())["live"]
TODAY = date(2026, 11, 6)


class FixedDate(date):
    @classmethod
    def today(cls):
        return TODAY


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(ibkr, "date", FixedDate)
    client = Mock()
    client.errorEvent = Event()
    client.wrapper = SimpleNamespace(ticker2ReqId={"mktData": {}})

    async def qualify(contract):
        contract.conId = 265598
        contract.localSymbol = contract.symbol
        if contract.secType == "STK":
            contract.primaryExchange = "NASDAQ"
        return [contract]

    client.qualifyContractsAsync = AsyncMock(side_effect=qualify)
    client.reqContractDetailsAsync = AsyncMock(side_effect=lambda contract: [SimpleNamespace(
        contract=contract, longName="APPLE INC", timeZoneId="US/Eastern",
    )])

    def request(contract, generic_ticks, snapshot, regulatory_snapshot):
        record = LIVE.get(contract.symbol, LIVE["AAPL"])
        ticker = Ticker(contract=contract, time=datetime(2026, 11, 6, 0, 30, tzinfo=UTC))
        ticker.impliedVolatility = record["implied_volatility"]
        client.wrapper.ticker2ReqId["mktData"][ticker] = 7
        return ticker

    client.reqMktData = Mock(side_effect=request)
    client.reqHistoricalDataAsync = AsyncMock(return_value=[])
    monkeypatch.setattr(ibkr, "IB", lambda: client)
    instance = IBKRProvider()
    instance.market_data_type = 3
    instance._ensure_connection = AsyncMock()
    instance._disconnect = AsyncMock()
    return instance


@pytest.mark.parametrize("symbol,sec_type,exchange", [
    ("AAPL", "stock", "SMART"), ("SPY", "etf", "SMART"),
    ("SPX", "index", "CBOE"), ("NDX", "index", "NASDAQ"),
    ("RUT", "index", "RUSSELL"), ("VIX", "index", "CBOE"),
])
async def test_snapshot_contracts_and_shape(provider, symbol, sec_type, exchange):
    result = await provider.get_implied_volatility(symbol.lower(), sec_type)
    assert isinstance(provider, BaseVolatilityProvider)
    contract = provider.ib.reqMktData.call_args.args[0]
    assert contract.exchange == exchange
    assert contract.secType == ("IND" if sec_type == "index" else "STK")
    provider.ib.reqMktData.assert_called_once_with(contract, "106", False, False)
    provider.ib.cancelMktData.assert_called_once_with(contract)
    assert result.symbol == symbol
    assert result.source_instrument == symbol
    assert result.method == "provider_model_30d"
    assert result.underlying_name == "APPLE INC"
    assert result.as_of == date(2026, 11, 5)
    assert [tenor.tenor_days for tenor in result.implied] == [30, 60, 90]
    assert result.implied[0].iv_call is None and result.implied[0].iv_put is None
    assert result.implied[0].iv.as_tuple().exponent == -4
    assert all(tenor.iv is None for tenor in result.implied[1:])
    assert len(provider.ib.errorEvent) == 0
    provider._disconnect.assert_awaited_once()


@pytest.mark.parametrize(
    "qualified",
    [[], [None], [[Future("ES")]]],
    ids=["empty", "missing", "ambiguous"],
)
@pytest.mark.parametrize("sec_type", ["stock", "etf", "index"])
async def test_unqualified_snapshot_contract_is_not_found(provider, qualified, sec_type):
    provider.ib.qualifyContractsAsync.side_effect = None
    provider.ib.qualifyContractsAsync.return_value = qualified

    with pytest.raises(DataNotFoundError):
        await provider.get_implied_volatility("AAPL", sec_type)

    provider.ib.reqContractDetailsAsync.assert_not_awaited()
    provider.ib.reqMktData.assert_not_called()
    provider._disconnect.assert_awaited_once()


async def test_snapshot_unknown_timezone_falls_back_to_utc(provider):
    provider.ib.reqContractDetailsAsync.side_effect = lambda contract: [
        SimpleNamespace(contract=contract, timeZoneId="Unknown/Timezone")
    ]

    result = await provider.get_implied_volatility("AAPL")

    assert result.as_of == date(2026, 11, 6)


def future_details(symbol, expiry, exchange, local_symbol):
    return SimpleNamespace(
        contract=Future(symbol, expiry, exchange=exchange, conId=123, localSymbol=local_symbol),
        longName=f"{symbol} future", timeZoneId="US/Central", realExpirationDate="",
    )


@pytest.mark.parametrize("root,exchange", [("ES", "CME"), ("CL", "NYMEX"), ("ZN", "CBOT"), ("GC", "COMEX")])
async def test_front_month_uses_seven_day_buffer(provider, root, exchange):
    near = future_details(root, "20261112", exchange, f"{root}X6")
    front = future_details(root, "20261113", exchange, f"{root}Z6")
    later = future_details(root, "20261218", exchange, f"{root}F7")
    provider.ib.reqContractDetailsAsync = AsyncMock(return_value=[later, near, front])
    result = await provider.get_implied_volatility(root, "future")
    query = provider.ib.reqContractDetailsAsync.call_args.args[0]
    assert query.symbol == root and query.exchange == exchange
    assert provider.ib.reqMktData.call_args.args[0] is front.contract
    assert result.source_instrument == f"{root}Z6"
    assert result.underlying_name == f"{root} future"
    assert result.market == exchange


async def test_unknown_futures_root_requires_one_exchange(provider):
    provider.ib.reqContractDetailsAsync = AsyncMock(return_value=[
        future_details("TEST", "20261218", "CME", "TESTZ6"),
        future_details("TEST", "20261218", "CBOT", "TESTZ6"),
    ])
    with pytest.raises(DataValidationError) as error:
        await provider.get_implied_volatility("TEST", "future")
    assert error.value.details["exchanges"] == ["CBOT", "CME"]
    provider.ib.reqMktData.assert_not_called()
    provider.ib.reqContractDetailsAsync.return_value = [future_details("TEST", "20261218", "CME", "TESTZ6")]
    assert (await provider.get_implied_volatility("TEST", "future")).source_instrument == "TESTZ6"


async def test_future_uses_real_expiration_date_when_contract_only_has_month(provider):
    detail = future_details("ES", "202612", "CME", "ESZ6")
    detail.realExpirationDate = "20261218"
    provider.ib.reqContractDetailsAsync = AsyncMock(return_value=[detail])
    assert (await provider.get_implied_volatility("ES", "future")).source_instrument == "ESZ6"


async def test_no_eligible_future(provider):
    provider.ib.reqContractDetailsAsync = AsyncMock(return_value=[future_details("ES", "20261112", "CME", "ESX6")])
    with pytest.raises(DataNotFoundError):
        await provider.get_implied_volatility("ES", "future")
    provider.ib.reqMktData.assert_not_called()


@pytest.mark.parametrize("include_valid", [False, True])
async def test_future_details_without_contract_are_ignored(provider, include_valid):
    details = [ContractDetails()]
    if include_valid:
        details.append(future_details("ES", "20261218", "CME", "ESZ6"))
    provider.ib.reqContractDetailsAsync = AsyncMock(return_value=details)

    if include_valid:
        result = await provider.get_implied_volatility("ES", "future")
        assert result.source_instrument == "ESZ6"
    else:
        with pytest.raises(DataNotFoundError) as error:
            await provider.get_implied_volatility("ES", "future")
        assert error.value.details["reason"] == "no_iv_data"
        provider.ib.reqMktData.assert_not_called()


@pytest.mark.parametrize("invalid", [None, float("nan"), float("inf"), 0, -1])
async def test_tick_timeout_always_cancels(provider, monkeypatch, invalid):
    monkeypatch.setattr(settings, "IBKR_IV_TIMEOUT_SECONDS", 0.002)
    ticker = Ticker()
    ticker.impliedVolatility = invalid
    provider.ib.reqMktData.side_effect = lambda *args: ticker
    with pytest.raises(DataNotFoundError) as error:
        await provider.get_implied_volatility("AAPL")
    assert error.value.details["reason"] == "no_iv_data"
    provider.ib.cancelMktData.assert_called_once()
    provider._disconnect.assert_awaited_once()
    assert len(provider.ib.errorEvent) == 0


@pytest.mark.parametrize("code", [354, 10089])
async def test_delayed_fallback_on_subscription_error(provider, code):
    provider.market_data_type = 1
    provider.ib.errorEvent += provider._on_ib_error
    original = provider.ib.reqMktData.side_effect

    def request(*args):
        if provider.ib.reqMktData.call_count == 1:
            provider.ib.errorEvent.emit(7, code, "Not subscribed", args[0])
            ticker = Ticker()
            provider.ib.wrapper.ticker2ReqId["mktData"][ticker] = 7
            return ticker
        return original(*args)

    provider.ib.reqMktData.side_effect = request
    result = await provider.get_implied_volatility("AAPL")
    assert result.implied[0].iv == Decimal("0.2519")
    assert [call.args[0] for call in provider.ib.reqMarketDataType.call_args_list] == [1, 3, 1]
    assert provider.ib.cancelMktData.call_count == 2
    assert len(provider.ib.errorEvent) == 1
    assert not provider._level1_subscription_error
    assert provider._subscription_errors == []
    assert provider._volatility_request_ids == set()


@pytest.mark.parametrize("fallback_enabled,configured_type,expected_calls", [(True, 1, 2), (False, 1, 1), (True, 3, 1)])
async def test_not_entitled_after_fallback(provider, fallback_enabled, configured_type, expected_calls):
    provider.market_data_type = configured_type
    provider.fallback_on_subscription_error = fallback_enabled

    def request(*args):
        provider.ib.errorEvent.emit(7, 354, "Not subscribed", args[0])
        return Ticker(impliedVolatility=float("nan"))

    provider.ib.reqMktData.side_effect = request
    with pytest.raises(ProviderError) as error:
        await provider.get_implied_volatility("AAPL")
    assert error.value.code == "PROVIDER_NOT_AVAILABLE"
    assert error.value.details["reason"] == "not_entitled"
    assert provider.ib.reqMktData.call_count == expected_calls
    assert provider.ib.cancelMktData.call_count == expected_calls
    assert len(provider.ib.errorEvent) == 0


async def test_unrelated_subscription_error_does_not_break_request(provider):
    ticker = Ticker(impliedVolatility=float("nan"))
    provider.ib.wrapper.ticker2ReqId["mktData"][ticker] = 7

    def request(*args):
        def update():
            provider.ib.errorEvent.emit(99, 354, "Other request not subscribed", args[0])
            ticker.impliedVolatility = 0.25
        asyncio.get_running_loop().call_soon(update)
        return ticker

    provider.ib.reqMktData.side_effect = request
    assert (await provider.get_implied_volatility("AAPL")).implied[0].iv == Decimal("0.2500")


def history_bars(filename):
    bars = BarDataList()
    bars.reqId = 8
    with (FIXTURES / filename).open() as file:
        for row in csv.DictReader(file):
            bars.append(BarData(date=date.fromisoformat(row["date"]), close=float(row["close"])))
    return bars


@pytest.mark.parametrize("symbol,sec_type,filename", [("AAPL", "stock", "H_AAPL.csv"), ("SPX", "index", "H_SPX.csv")])
async def test_history_fixture_parsing(provider, symbol, sec_type, filename):
    bars = history_bars(filename)
    bars.reverse()
    bars.extend(BarData(date=date(2026, 10, 25), close=value) for value in (0, -1, float("nan"), float("inf")))
    provider.ib.reqHistoricalDataAsync.return_value = bars
    result = await provider.get_implied_volatility_history(symbol, date(2026, 10, 20), TODAY, sec_type=sec_type)
    assert result.points[-1].date == TODAY
    assert result.points[-1].iv == Decimal("0.2524" if symbol == "AAPL" else "0.1762")
    assert all(point.iv_call is None and point.iv_put is None for point in result.points)
    assert all(date(2026, 10, 20) <= point.date <= TODAY for point in result.points)
    assert [point.date for point in result.points] == sorted(point.date for point in result.points)
    request = provider.ib.reqHistoricalDataAsync.call_args.kwargs
    assert request["whatToShow"] == "OPTION_IMPLIED_VOLATILITY"
    assert request["barSizeSetting"] == "1 day" and request["useRTH"] is True
    assert request["endDateTime"] == "" and request["timeout"] == 0
    provider._disconnect.assert_awaited_once()


@pytest.mark.parametrize("days,expected", [(30, "30 D"), (365, "365 D"), (366, "2 Y")])
async def test_history_duration_and_end_time(provider, days, expected):
    end = TODAY - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    provider.ib.reqHistoricalDataAsync.return_value = [BarData(date=end, close=0.2)]
    await provider.get_implied_volatility_history("AAPL", start, end)
    request = provider.ib.reqHistoricalDataAsync.call_args.kwargs
    assert request["durationStr"] == expected
    assert request["endDateTime"].isoformat() == "2026-11-05T23:59:59-05:00"


@pytest.mark.parametrize("method,kwargs,error_type", [
    ("get_implied_volatility", {"ric": "AAPLATMIV.U"}, DataValidationError),
    ("get_implied_volatility_history", {"ric": "AAPLATMIV.U"}, DataValidationError),
    ("get_implied_volatility_history", {"sec_type": "future"}, CapabilityNotSupportedError),
    ("get_implied_volatility_history", {"tenor_days": 60}, CapabilityNotSupportedError),
    ("get_implied_volatility_history", {"tenor_days": 45}, DataValidationError),
])
async def test_unsupported_requests_never_connect(provider, method, kwargs, error_type):
    args = ["AAPL"] if method == "get_implied_volatility" else ["AAPL", TODAY - timedelta(days=30), TODAY]
    with pytest.raises(error_type):
        await getattr(provider, method)(*args, **kwargs)
    provider._ensure_connection.assert_not_awaited()
    provider.ib.reqHistoricalDataAsync.assert_not_awaited()


@pytest.mark.parametrize("error,expected", [
    (RuntimeError("HMDS query returned no data"), DataNotFoundError),
    (TimeoutError(), ProviderTimeoutError),
    (ConnectionError("connection lost"), ProviderConnectionError),
    (RuntimeError("10089 Not subscribed"), ProviderError),
])
async def test_history_error_mapping(provider, error, expected):
    provider.ib.reqHistoricalDataAsync.side_effect = error
    with pytest.raises(expected):
        await provider.get_implied_volatility_history("AAPL", TODAY - timedelta(days=30), TODAY)
    assert len(provider.ib.errorEvent) == 0
    provider._disconnect.assert_awaited_once()


async def test_history_timeout_is_not_no_data(provider):
    provider.timeout_seconds = 0.002

    async def stall(*args, **kwargs):
        await asyncio.sleep(10)

    provider.ib.reqHistoricalDataAsync.side_effect = stall
    with pytest.raises(ProviderTimeoutError):
        await provider.get_implied_volatility_history("AAPL", TODAY - timedelta(days=30), TODAY)


async def test_history_request_scoped_entitlement_error(provider):
    provider.market_data_type = 1
    provider.ib.errorEvent += provider._on_ib_error
    bars = BarDataList()
    bars.reqId = 8

    async def history(*args, **kwargs):
        provider.ib.errorEvent.emit(99, 354, "Other request", args[0])
        provider.ib.errorEvent.emit(8, 10089, "API data unavailable", args[0])
        return bars

    provider.ib.reqHistoricalDataAsync.side_effect = history
    with pytest.raises(ProviderError) as error:
        await provider.get_implied_volatility_history("AAPL", TODAY - timedelta(days=30), TODAY)
    assert error.value.details["reason"] == "not_entitled"
    assert not provider._level1_subscription_error
    assert provider._subscription_errors == []


async def test_existing_rut_index_price_uses_russell(provider):
    ticker = Ticker()
    ticker.last = 2200
    provider._get_tickers_snapshot = AsyncMock(return_value=[ticker])
    provider._get_market_open_status = AsyncMock(return_value=True)
    result = await provider.get_last_price("RUT", sec_type="index")
    assert result.price == Decimal(2200)
    contract = provider.ib.qualifyContractsAsync.call_args.args[0]
    assert contract.symbol == "RUT" and contract.exchange == "RUSSELL"
