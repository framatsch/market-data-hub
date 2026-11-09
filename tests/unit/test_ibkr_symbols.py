"""IBKR native mapping of canonical (root, sec_type) for prices."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from eventkit import Event
from ib_async import ContFuture, Future, Index, Stock, Ticker
from ib_async.objects import BarData

from app.providers import ibkr
from app.providers.ibkr import IBKRProvider
from app.utils.errors import ProviderError, ProviderNotEntitledError

NOW = datetime(2026, 11, 6, 15, tzinfo=UTC)


def future_details(symbol, expiry, exchange, local_symbol):
    return SimpleNamespace(
        contract=Future(symbol, expiry, exchange=exchange, conId=123, localSymbol=local_symbol, currency="USD"),
        longName=f"{symbol} future", timeZoneId="US/Central", realExpirationDate="",
    )


def priced_ticker(contract, price=5000.0):
    ticker = Ticker(contract=contract, time=NOW)
    ticker.last = price
    ticker.close = price
    return ticker


@pytest.fixture
def provider(monkeypatch):
    client = Mock()
    client.errorEvent = Event()
    client.wrapper = SimpleNamespace(ticker2ReqId={"mktData": {}})

    async def qualify(contract):
        contract.conId = 1
        contract.currency = "USD"
        return [contract]

    client.qualifyContractsAsync = AsyncMock(side_effect=qualify)
    client.reqContractDetailsAsync = AsyncMock(return_value=[])
    client.reqHistoricalDataAsync = AsyncMock(return_value=[])
    monkeypatch.setattr(ibkr, "IB", lambda: client)
    instance = IBKRProvider()
    instance.market_data_type = 3
    instance._ensure_connection = AsyncMock()
    instance._disconnect = AsyncMock()
    instance._get_market_open_status = AsyncMock(return_value=True)
    instance._get_tickers_snapshot = AsyncMock(
        side_effect=lambda contracts: [priced_ticker(contracts[0])]
    )
    return instance


def test_declares_price_support_but_stock_etf_option_underlyings():
    assert IBKRProvider.price_sec_types == {"stock", "etf", "index", "future"}
    assert IBKRProvider.price_history_sec_types == {"stock", "etf", "index", "future"}
    assert IBKRProvider.option_underlying_sec_types == {"stock", "etf"}


async def test_stock_has_no_source_instrument(provider):
    quote = await provider.get_last_price("AAPL", sec_type="stock")
    contract = provider._get_tickers_snapshot.call_args.args[0][0]
    assert isinstance(contract, Stock)
    assert quote.source_instrument is None
    assert quote.symbol == "AAPL"


async def test_index_with_deviating_root_uses_ibkr_symbol(provider):
    quote = await provider.get_last_price("DJI", sec_type="index")
    contract = provider._get_tickers_snapshot.call_args.args[0][0]
    assert isinstance(contract, Index)
    assert contract.symbol == "INDU" and contract.exchange == "NYSE"
    assert quote.source_instrument == "INDU"


async def test_unknown_index_root_passes_through(provider):
    quote = await provider.get_last_price("OEX", sec_type="index")
    contract = provider._get_tickers_snapshot.call_args.args[0][0]
    assert contract.symbol == "OEX"
    assert quote.source_instrument is None


async def test_future_last_price_uses_concrete_front_month(provider):
    provider.ib.reqContractDetailsAsync.return_value = [
        future_details("ES", "20261218", "CME", "ESZ6"),
        future_details("ES", "20261112", "CME", "ESX6"),
        future_details("ES", "20270319", "CME", "ESH7"),
    ]
    quote = await provider.get_last_price("ES", sec_type="future")
    lookup = provider.ib.reqContractDetailsAsync.call_args.args[0]
    assert lookup.symbol == "ES" and lookup.exchange == "CME"
    traded = provider._get_tickers_snapshot.call_args.args[0][0]
    assert traded.localSymbol == "ESZ6" and traded.conId == 123
    assert quote.source_instrument == "ESZ6"
    assert quote.currency == "USD"
    provider.ib.qualifyContractsAsync.assert_not_awaited()


async def test_future_without_eligible_contract_is_not_found(provider):
    provider.ib.reqContractDetailsAsync.return_value = [
        future_details("ES", "20261112", "CME", "ESX6")
    ]
    with pytest.raises(ProviderError) as error:
        await provider.get_last_price("ES", sec_type="future")
    assert "MarketData" in error.value.message
    provider._get_tickers_snapshot.assert_not_awaited()


async def test_future_history_requests_continuous_series(provider):
    bar = BarData(date=NOW.date(), open=1, high=2, low=1, close=2, volume=5)
    provider.ib.reqHistoricalDataAsync.return_value = [bar]
    bars = await provider.get_historical_prices(
        "ES", "1d", NOW - timedelta(days=5), NOW, sec_type="future"
    )
    contract = provider.ib.reqHistoricalDataAsync.call_args.args[0]
    assert isinstance(contract, ContFuture)
    assert contract.symbol == "ES" and contract.exchange == "CME"
    provider.ib.reqContractDetailsAsync.assert_not_awaited()
    assert bars[0].symbol == "ES"


async def test_unknown_future_history_resolves_exchange_first(provider):
    provider.ib.reqContractDetailsAsync.return_value = [
        future_details("TEST", "20261218", "CME", "TESTZ6")
    ]
    await provider.get_historical_prices(
        "TEST", "1d", NOW - timedelta(days=5), NOW, sec_type="future"
    )
    contract = provider.ib.reqHistoricalDataAsync.call_args.args[0]
    assert isinstance(contract, ContFuture) and contract.exchange == "CME"


async def test_index_history_marks_source_instrument(provider):
    provider.ib.reqHistoricalDataAsync.return_value = [
        BarData(date=NOW.date(), open=1, high=2, low=1, close=2, volume=5)
    ]
    bars = await provider.get_historical_prices(
        "DJI", "1d", NOW - timedelta(days=5), NOW, sec_type="index"
    )
    contract = provider.ib.reqHistoricalDataAsync.call_args.args[0]
    assert isinstance(contract, Index) and contract.symbol == "INDU"
    assert bars[0].source_instrument == "INDU"


async def test_last_price_fallback_keeps_index_contract(provider):
    provider._get_tickers_snapshot = AsyncMock(
        side_effect=lambda contracts: [Ticker(contract=contracts[0])]
    )
    provider.ib.reqHistoricalDataAsync.return_value = [
        BarData(date=NOW.date(), open=1, high=2, low=1, close=4321.5, volume=5)
    ]
    quote = await provider.get_last_price("SPX", sec_type="index")
    contract = provider.ib.reqHistoricalDataAsync.call_args.args[0]
    assert isinstance(contract, Index) and contract.symbol == "SPX"
    assert quote.price == Decimal("4321.5")


async def test_last_price_fallback_keeps_front_month_future(provider):
    provider.ib.reqContractDetailsAsync.return_value = [
        future_details("ES", "20261218", "CME", "ESZ6")
    ]
    provider._get_tickers_snapshot = AsyncMock(
        side_effect=lambda contracts: [Ticker(contract=contracts[0])]
    )
    provider.ib.reqHistoricalDataAsync.return_value = [
        BarData(date=NOW.date(), open=1, high=2, low=1, close=5000, volume=5)
    ]
    quote = await provider.get_last_price("ES", sec_type="future")
    assert provider.ib.reqHistoricalDataAsync.call_args.args[0].localSymbol == "ESZ6"
    assert quote.source_instrument == "ESZ6"


async def test_entitlement_error_after_fallback_also_fails(provider):
    def snapshot(contracts):
        provider.ib.errorEvent.emit(5, 354, "Not subscribed", contracts[0])
        return [Ticker(contract=contracts[0])]

    provider._get_tickers_snapshot = AsyncMock(side_effect=snapshot)
    with pytest.raises(ProviderNotEntitledError) as error:
        await provider.get_last_price("SPX", sec_type="index")
    assert error.value.code == "PROVIDER_NOT_ENTITLED"
    assert error.value.details["symbol"] == "I:SPX"
    assert error.value.details["instrument"] == "SPX"
    assert "354" in error.value.details["provider_message"]
    assert len(provider.ib.errorEvent) == 0


async def test_fallback_data_takes_precedence_over_entitlement_error(provider):
    def snapshot(contracts):
        provider.ib.errorEvent.emit(5, 10089, "Delayed data only", contracts[0])
        return [Ticker(contract=contracts[0])]

    provider._get_tickers_snapshot = AsyncMock(side_effect=snapshot)
    provider.ib.reqHistoricalDataAsync.return_value = [
        BarData(date=NOW.date(), open=1, high=2, low=1, close=7, volume=5)
    ]
    quote = await provider.get_last_price("SPX", sec_type="index")
    assert quote.price == Decimal(7)


async def test_other_instruments_errors_are_ignored(provider):
    def snapshot(contracts):
        provider.ib.errorEvent.emit(5, 354, "Other", Stock("MSFT", conId=999))
        return [Ticker(contract=contracts[0])]

    provider._get_tickers_snapshot = AsyncMock(side_effect=snapshot)
    quote = await provider.get_last_price("AAPL")
    assert quote.price == Decimal("0.0")


async def test_level_one_without_data_is_not_entitled(provider):
    provider.market_data_type = 1
    provider._get_tickers_snapshot = AsyncMock(
        side_effect=lambda contracts: [Ticker(contract=contracts[0])]
    )
    with pytest.raises(ProviderNotEntitledError) as error:
        await provider.get_last_price("AAPL", market_data_type=1)
    assert error.value.details["symbol"] == "AAPL"
    provider.ib.reqHistoricalDataAsync.assert_not_awaited()


async def test_history_permission_error_is_not_entitled(provider):
    provider.ib.reqHistoricalDataAsync.side_effect = RuntimeError(
        "Error 162: no market data permissions for CME"
    )
    with pytest.raises(ProviderNotEntitledError) as error:
        await provider.get_historical_prices(
            "ES", "1d", NOW - timedelta(days=5), NOW, sec_type="future"
        )
    assert error.value.details["symbol"] == "F:ES"
    assert "no market data permissions" in error.value.details["provider_message"]
