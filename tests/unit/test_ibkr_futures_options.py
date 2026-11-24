"""TWS futures chains using the contracts verified on the paper Web gateway."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from ib_async import ContractDetails, Future, FuturesOption, Ticker

from app.providers.ibkr import IBKRProvider
from app.utils.errors import CapabilityNotSupportedError, DataValidationError, ProviderConnectionError

FOPS = json.loads((Path(__file__).parents[1] / "fixtures/ibkrweb/futures_option_secdef.json").read_text())


def contract_details(root):
    rows = []
    for bucket, listings in FOPS["secdef_info"].items():
        if not bucket.startswith(f"{root}:"):
            continue
        for row in listings:
            identity = FOPS["contract_info"].get(str(row["conid"]))
            if identity is None:
                continue
            rows.append(ContractDetails(
                contract=FuturesOption(
                    root, row["maturityDate"], row["strike"], row["right"], row["exchange"],
                    row["multiplier"], currency="USD", conId=row["conid"],
                    tradingClass=row["tradingClass"], localSymbol=identity["local_symbol"],
                ),
                underConId=identity["underlying_con_id"],
                realExpirationDate=row["maturityDate"],
            ))
    return rows


@pytest.fixture
def provider():
    provider = IBKRProvider()
    provider._ensure_connection = AsyncMock()
    provider._disconnect = AsyncMock()
    provider.ib.reqSecDefOptParamsAsync = AsyncMock(side_effect=AssertionError("Equity lookup used for futures"))
    provider.ib.reqContractDetailsAsync = AsyncMock(side_effect=lambda request: contract_details(request.symbol))

    def qualify(future):
        info = FOPS["contract_info"][str(future.conId)]
        return [Future(conId=future.conId, localSymbol=info["local_symbol"], exchange=info["exchange"])]

    provider.ib.qualifyContractsAsync = AsyncMock(side_effect=qualify)
    def snapshot(batch):
        tickers = []
        for contract in batch:
            ticker = Ticker(contract=contract)
            if contract.secType == "FUT":
                ticker.last, ticker.close = 0.0, 80.5
            else:
                ticker.bid, ticker.ask = 1.5, 1.6
                ticker.callOpenInterest, ticker.putOpenInterest = 10, 11
            tickers.append(ticker)
        return tickers

    provider._get_tickers_snapshot = AsyncMock(side_effect=snapshot)
    return provider


@pytest.mark.parametrize("root,expiry,exchange,multiplier,requested,selected,future", [
    ("ES", date(2026, 11, 27), "CME", 50, None, "EW4", "ESZ6"),
    ("ES", date(2026, 12, 18), "CME", 50, None, "ES", "ESZ6"),
    ("ES", date(2026, 12, 18), "CME", 50, "eW3", "EW3", "ESH7"),
    ("CL", date(2026, 12, 16), "NYMEX", 1000, None, "LO", "CLF7"),
    ("CL", date(2026, 12, 16), "NYMEX", 1000, "wl3", "WL3", "CLG7"),
])
async def test_futures_option_chain_requests_fop_and_prepares_one_snapshot(
    provider, root, expiry, exchange, multiplier, requested, selected, future,
):
    strike = Decimal(7250 if root == "ES" else 60)
    chain = await provider.get_option_chain(
        root, expiry, strike, strike, sec_type="future", trading_class=requested, right="put",
    )
    (request,) = provider.ib.reqContractDetailsAsync.call_args.args
    assert isinstance(request, FuturesOption)
    assert (request.symbol, request.lastTradeDateOrContractMonth, request.exchange, request.right) == (
        root, expiry.strftime("%Y%m%d"), exchange, "P",
    )
    assert chain.underlying_symbol == f"F:{root}"
    assert (chain.underlying_contract, chain.exchange, chain.multiplier, chain.trading_class) == (
        future, exchange, multiplier, selected,
    )
    assert chain.underlying_price == Decimal(0)  # zero last beats the close
    (quote,) = chain.options
    assert quote.symbol.startswith(selected) and " P" in quote.symbol
    assert (quote.strike, quote.type, quote.open_interest) == (strike, "put", 11)
    (snapshot,) = provider._get_tickers_snapshot.call_args.args
    assert [contract.secType for contract in snapshot] == ["FUT", "FOP"]
    provider._disconnect.assert_awaited_once()


async def test_futures_option_empty_expiry_class_or_window(provider):
    expiry = date(2026, 12, 18)
    empty = await provider.get_option_chain("ES", expiry, sec_type="future", trading_class="bad")
    unlisted = await provider.get_option_chain("ES", date(2026, 12, 20), sec_type="future")
    outside = await provider.get_option_chain("ES", expiry, Decimal(7400), sec_type="future")
    assert empty.options == unlisted.options == outside.options == []
    assert empty.trading_class is None and outside.trading_class == "ES"
    provider._get_tickers_snapshot.assert_not_awaited()


async def test_futures_option_chain_ambiguity_preserves_422(provider):
    rows = contract_details("ES")
    for row in rows:
        if row.contract.tradingClass == "ES":
            row.contract.tradingClass = "E3A"
    provider.ib.reqContractDetailsAsync.return_value = rows
    provider.ib.reqContractDetailsAsync.side_effect = None
    with pytest.raises(DataValidationError) as exc:
        await provider.get_option_chain("ES", date(2026, 12, 18), sec_type="future")
    assert exc.value.details["trading_classes"] == ["E3A", "EW3"]
    provider._get_tickers_snapshot.assert_not_awaited()


async def test_futures_option_connection_error_matches_equities(provider):
    provider._ensure_connection.side_effect = ProviderConnectionError("Gateway offline")
    for symbol, sec_type in (("ES", "future"), ("AAPL", "stock")):
        with pytest.raises(ProviderConnectionError, match="Gateway offline"):
            await provider.get_option_chain(symbol, date(2026, 12, 18), sec_type=sec_type)
    provider.ib.reqContractDetailsAsync.assert_not_awaited()
    assert provider._disconnect.await_count == 2


async def test_futures_option_unsupported_root_does_not_connect(provider):
    with pytest.raises(CapabilityNotSupportedError) as exc:
        await provider.get_option_chain("NQ", date(2026, 12, 18), sec_type="future")
    assert exc.value.details["supported"] == ["CL", "ES"]
    provider._ensure_connection.assert_not_awaited()
