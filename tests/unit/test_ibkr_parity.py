"""Parity between the TWS provider (``ibkr``) and the Web API provider (``ibkrweb``).

Both providers are driven with the same market (AAPL, SPX, ES, one option) through
their own transport: ``ib_async`` is replaced by an in-memory fake, the Client Portal
Gateway by ``httpx.MockTransport`` with the recorded fixtures. Every scenario asserts
that the two providers answer with the same models, units, symbols and error codes.

Differences that are intentional are asserted explicitly in ``test_declared_gaps``.
The providers emit the root symbol differently (``ibkr`` the raw root, ``ibkrweb`` the
canonical form); services overwrite it either way, so it is normalised the same way.
"""

import json
import math
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.config import settings
from app.providers.base import BaseNewsProvider
from app.providers.ibkr import IBKRProvider
from app.providers.ibkr_web import IbkrWebProvider
from app.providers.ibkr_web_config import IbkrWebConnectionConfig
from app.providers.ibkr_web_contracts import IbkrWebContracts
from app.providers.ibkr_web_session import GatewayPacer, IbkrWebSession
from app.utils.errors import (
    CapabilityNotSupportedError,
    DataNotFoundError,
    ProviderNotEntitledError,
)
from app.utils.symbols import canonical_symbol

DATA = json.loads((Path(__file__).parents[1] / "fixtures/ibkrweb/gateway_responses.json").read_text())
SEARCH = "iserver/secdef/search"
SNAPSHOT = "iserver/marketdata/snapshot"
HISTORY = "iserver/marketdata/history"
SCHEDULE = "contract/trading-schedule"
NAN = math.nan
EXPIRY = date(2026, 12, 18)
CALL_ID, PUT_ID = "AAPL  261218C00350000", "AAPL  261218P00350000"
UPDATED = datetime.fromtimestamp(DATA["snapshot"][0]["_updated"] / 1000, UTC)
MINUTE_BARS = [(datetime.fromtimestamp(row["t"] / 1000, UTC), row) for row in DATA["history_minute"]["data"]]


# ---------------------------------------------------------------- TWS side (ib_async)


class Tick(SimpleNamespace):
    __hash__ = object.__hash__  # IBKRProvider keys its request ids by ticker


def ticker(contract=None, **values):
    base = {"bid": NAN, "ask": NAN, "last": NAN, "close": NAN, "volume": NAN, "time": None, "contract": contract,
            "callOpenInterest": NAN, "putOpenInterest": NAN, "modelGreeks": None, "impliedVolatility": NAN}
    return Tick(**{**base, **values})


def tws_option(contract):
    if contract.right != "C":
        return None
    return SimpleNamespace(impliedVol=0.248, delta=0.519, gamma=0.016, vega=0.391, theta=-0.189)


class FakeIB:
    """Just enough of ``ib_async.IB`` for one market scenario."""

    def __init__(self, *, front_expiry, last_price_row=True):
        self.errorEvent = MagicMock()
        self.wrapper = SimpleNamespace(ticker2ReqId={})
        self.front_expiry = front_expiry
        self.last_price_row = last_price_row
        self.history_calls = []
        self.mkt_data_calls = []

    def isConnected(self):
        return True

    def disconnect(self):
        pass

    def reqMarketDataType(self, _value):
        pass

    def cancelMktData(self, _contract):
        pass

    async def qualifyContractsAsync(self, *contracts):
        for contract in contracts:
            known = {"AAPL": 265598, "SPX": 416904, "SPY": 756733}.get(contract.symbol)
            if contract.secType == "OPT":
                if contract.localSymbol and contract.localSymbol not in (CALL_ID, PUT_ID):
                    continue
                if contract.localSymbol:  # option_id given, fields come from the gateway
                    contract.right = contract.localSymbol[12]
                    contract.strike = float(int(contract.localSymbol[13:]) / 1000)
                    contract.lastTradeDateOrContractMonth = "20" + contract.localSymbol[6:12]
                else:
                    contract.localSymbol = (
                        f"{contract.symbol:<6}{contract.lastTradeDateOrContractMonth[2:]}"
                        f"{contract.right}{int(contract.strike * 1000):08d}"
                    )
                contract.conId = 692808279 if contract.right == "C" else 692809971
            elif known:
                contract.conId = known
                contract.currency = "USD"
                contract.localSymbol = contract.symbol
                contract.primaryExchange = "NASDAQ" if contract.symbol == "AAPL" else ""
            else:
                return [None]
        return list(contracts)

    async def reqContractDetailsAsync(self, contract):
        if contract.secType == "FUT":
            future = SimpleNamespace(
                secType="FUT", symbol=contract.symbol, localSymbol="ESZ6", exchange="CME", currency="USD",
                lastTradeDateOrContractMonth=self.front_expiry.strftime("%Y%m%d"), primaryExchange="", conId=1,
            )
            return [SimpleNamespace(contract=future, tradingHours="", timeZoneId="US/Eastern", longName="E-mini")]
        return [SimpleNamespace(contract=contract, tradingHours="", timeZoneId="US/Eastern", longName="APPLE INC")]

    def reqMktData(self, contract, generic_ticks="", snapshot=False, _regulatory=False):
        self.mkt_data_calls.append((contract.symbol, contract.secType, generic_ticks))
        if contract.secType == "OPT":
            call = contract.right == "C"
            return ticker(contract, last=10.15 if call else NAN, volume=3351 if call else NAN,
                          callOpenInterest=27600 if call else NAN, modelGreeks=tws_option(contract))
        if generic_ticks == "106":
            return ticker(contract, impliedVolatility=0.23601, time=UPDATED)
        if not self.last_price_row:
            return ticker(contract)
        price = {"AAPL": 348.80, "SPX": 7177.56, "ES": 7199.0}[contract.symbol]
        return ticker(contract, last=price, volume=39856904 if contract.symbol == "AAPL" else NAN, time=UPDATED)

    async def reqSecDefOptParamsAsync(self, *_args):
        return [SimpleNamespace(expirations=["20261218", "20261211"], strikes=[345.0, 347.5, 350.0])]

    async def reqHistoricalDataAsync(self, contract, **kwargs):
        self.history_calls.append((contract.secType, kwargs["barSizeSetting"]))
        if kwargs["barSizeSetting"] == "1 min":
            return [SimpleNamespace(date=stamp, open=row["o"], high=row["h"], low=row["l"], close=row["c"],
                                    volume=row["v"] * 40) for stamp, row in MINUTE_BARS]
        return [SimpleNamespace(date=date(2026, 11, 16) + timedelta(days=i), open=row["o"], high=row["h"],
                                low=row["l"], close=row["c"], volume=round(row["v"] * 40))
                for i, row in enumerate(DATA["history_daily"]["data"])]


class TwsBackend:
    name = "ibkr"

    def __init__(self, front_expiry):
        with patch("app.providers.ibkr.IB", return_value=FakeIB(front_expiry=front_expiry)):
            self.provider = IBKRProvider()
        self.ib = self.provider.ib
        self.provider.fallback_on_subscription_error = True

    def set_last_price_missing(self):
        self.ib.last_price_row = False

    async def close(self):
        pass


# ---------------------------------------------------------------- Web API side (CPGW)


class WebBackend:
    name = "ibkrweb"

    def __init__(self, front_expiry):
        self.front_expiry = front_expiry
        self.calls = []
        self.denied = False
        clock = 0.0

        async def advance(delay):
            nonlocal clock
            clock += delay

        gateway = IbkrWebSession(
            IbkrWebConnectionConfig.from_settings({}), timeout=1,
            transport=httpx.MockTransport(self.handle), pacer=GatewayPacer(6, clock=lambda: clock, sleep=advance),
        )
        self.provider = IbkrWebProvider(session=gateway)
        self.provider._contract_resolver = IbkrWebContracts(gateway, redis_backend=lambda: None)

    def set_last_price_missing(self):
        self.denied = True

    def handle(self, request):
        path = request.url.path.removeprefix("/v1/api/")
        params = dict(request.url.params)
        self.calls.append(path)
        if path == "iserver/auth/status":
            return httpx.Response(200, json=DATA["status_ready"])
        if path == "iserver/accounts":
            return httpx.Response(200, json=DATA["accounts"])
        if path == "trsrv/stocks":
            return httpx.Response(200, json=DATA["stocks"])
        if path == "trsrv/futures":
            day = int(self.front_expiry.strftime("%Y%m%d"))
            return httpx.Response(200, json={"ES": [{"symbol": "ES", "conid": 515416632, "ltd": day, "expirationDate": day}]})
        if path == "iserver/contract/515416632/info":
            return httpx.Response(200, json={"exchange": "CME", "local_symbol": "ESZ6", "currency": "USD"})
        if path == "iserver/contract/265598/info":
            return httpx.Response(200, json=DATA["contract_info"])
        if path == SEARCH:
            if params.get("symbol") == "SPX":
                return httpx.Response(200, json=DATA["search_SPX"])
            return httpx.Response(200, json=DATA["search_apple_name"] if params.get("name") else DATA["search_AAPL"])
        if path == "iserver/secdef/strikes":
            return httpx.Response(200, json=DATA["strikes"])
        if path == "iserver/secdef/info":
            return httpx.Response(200, json=DATA["option_info"])
        if path == SCHEDULE:
            return httpx.Response(404)
        if path == HISTORY:
            if params["bar"] == "1min":
                return httpx.Response(200, json=DATA["history_minute"])
            return httpx.Response(200, json=DATA["history_daily"])
        if path == SNAPSHOT:
            if self.denied:
                return httpx.Response(200, json=[{"conid": 265598, "6509": "N"}])
            return httpx.Response(200, json=DATA["snapshot"])
        raise AssertionError(f"unexpected gateway request {path}")

    async def close(self):
        await self.provider.close()


@pytest.fixture(params=["ibkr", "ibkrweb"])
async def backend(request, monkeypatch):
    monkeypatch.setattr(settings, "IBKRWEB_ALERT_WEBHOOK_URL", "")
    monkeypatch.setattr(settings, "IBKR_FALLBACK_ON_SUBSCRIPTION_ERROR", True)
    front = date.today() + timedelta(days=30)
    instance = TwsBackend(front) if request.param == "ibkr" else WebBackend(front)
    yield instance
    await instance.close()


@pytest.fixture
async def both(monkeypatch):
    monkeypatch.setattr(settings, "IBKRWEB_ALERT_WEBHOOK_URL", "")
    front = date.today() + timedelta(days=30)
    pair = TwsBackend(front), WebBackend(front)
    yield pair
    for item in pair:
        await item.close()


async def run(both, method, *args, **kwargs):
    """The same call on both providers, normalised like the services do."""
    results = []
    for item in both:
        results.append(await getattr(item.provider, method)(*args, **kwargs))
    return results


def normalised(model, symbol=None):
    update = {"provider": "x"}
    if symbol is not None:
        update["symbol"] = symbol
    return model.model_copy(update=update)


def same(left, right, *fields):
    assert type(left) is type(right)
    for field in fields:
        assert getattr(left, field) == getattr(right, field), field


# ---------------------------------------------------------------- scenarios


@pytest.mark.parametrize(("symbol", "sec_type", "price", "instrument"), [
    ("AAPL", "stock", "348.80", None),
    ("SPX", "index", "7177.56", None),
    ("ES", "future", "7199.00", "ESZ6"),
])
async def test_last_price_parity(both, symbol, sec_type, price, instrument):
    tws, web = await run(both, "get_last_price", symbol, sec_type=sec_type)
    same(tws, web, "price", "currency", "source_instrument", "bid", "ask", "is_market_open")
    assert tws.price == Decimal(price) and tws.source_instrument == instrument
    assert tws.currency == "USD"
    assert tws.timestamp.date() == web.timestamp.date() or sec_type != "stock"
    expected = canonical_symbol(symbol, sec_type)
    assert normalised(web).symbol == expected and web.symbol == expected
    if sec_type == "stock":
        assert tws.volume == web.volume == 39856904


@pytest.mark.parametrize("interval", ["1d", "1m"])
async def test_history_parity(both, interval):
    if interval == "1d":
        start, end = datetime(2026, 11, 16), datetime(2026, 11, 17)
    else:
        start, end = MINUTE_BARS[0][0] - timedelta(minutes=1), MINUTE_BARS[1][0] + timedelta(minutes=1)
    tws, web = await run(both, "get_historical_prices", "AAPL", interval, start, end, True)
    assert len(tws) == len(web) == 2
    for left, right in zip(tws, web, strict=True):
        same(left, right, "start", "open", "high", "low", "close", "volume", "source_instrument")
    assert tws[0].volume == (19302918 if interval == "1d" else 340)


async def test_option_chain_and_quote_parity(both):
    tws, web = await run(both, "get_option_chain", "AAPL", EXPIRY, Decimal(350), Decimal(350))
    assert tws.underlying_symbol == web.underlying_symbol == "AAPL" and tws.expiry == web.expiry == EXPIRY
    assert [o.symbol for o in tws.options] == [o.symbol for o in web.options] == [CALL_ID, PUT_ID]
    for left, right in zip(tws.options, web.options, strict=True):
        same(left, right, "symbol", "strike", "type", "price", "bid", "ask", "volume", "open_interest")
        for field in ("implied_volatility", "delta", "gamma", "vega", "theta"):
            assert getattr(left, field) == pytest.approx(getattr(right, field))
    call = tws.options[0]
    assert (call.price, call.volume, call.open_interest, call.implied_volatility) == (Decimal("10.15"), 3351, 27600, 0.248)
    tws_quote, web_quote = await run(both, "get_option_quote", "AAPL", CALL_ID)
    same(tws_quote, web_quote, "symbol", "underlying_symbol", "strike", "expiry", "type", "price", "volume",
         "open_interest")
    assert tws_quote.symbol == CALL_ID and tws_quote.implied_volatility == pytest.approx(web_quote.implied_volatility)


async def test_implied_volatility_snapshot_parity(both):
    tws, web = await run(both, "get_implied_volatility", "AAPL")
    same(tws, web, "symbol", "sec_type", "method", "source_instrument", "underlying", "underlying_name", "market",
         "implied")
    assert tws.implied[0].iv == web.implied[0].iv == Decimal("0.2360")
    assert abs((tws.as_of - web.as_of).days) <= 0


async def test_company_profile_and_search_parity(both):
    tws, web = await run(both, "get_company_profile", "AAPL")
    same(tws, web, "symbol", "currency")
    # declared difference: TWS qualifies on SMART without a long name, the gateway knows both
    assert (tws.name, tws.exchange) == ("AAPL", "SMART")
    assert (web.name, web.exchange, web.industry) == ("APPLE INC", "NASDAQ", "Computers")
    tws_hits, web_hits = await run(both, "search_companies", "aapl")
    assert [c.symbol for c in tws_hits] == [c.symbol for c in web_hits] == ["AAPL"]
    assert type(tws_hits[0]) is type(web_hits[0])


async def test_error_parity_entitlement_and_not_found(backend):
    backend.set_last_price_missing()
    with pytest.raises(ProviderNotEntitledError) as denied:
        await backend.provider.get_last_price("AAPL", market_data_type=1)
    assert denied.value.code == "PROVIDER_NOT_ENTITLED"
    assert denied.value.details["symbol"] == "AAPL"
    with pytest.raises(DataNotFoundError) as missing:
        await backend.provider.get_company_profile("ZZZZINVALID")
    assert missing.value.code == "DATA_NOT_FOUND"


async def test_declared_gaps(both):
    tws, web = both
    # news: only TWS serves it
    assert isinstance(tws.provider, BaseNewsProvider) and not isinstance(web.provider, BaseNewsProvider)
    # IV history: TWS answers for stocks (30d), the gateway has no source
    assert "stock" in tws.provider.volatility_history_sec_types
    assert web.provider.volatility_history_sec_types == frozenset()
    with pytest.raises(CapabilityNotSupportedError) as gap:
        await web.provider.get_implied_volatility_history("AAPL", date(2026, 10, 1), date(2026, 11, 1))
    assert gap.value.code == "CAPABILITY_NOT_SUPPORTED" and not web.calls
    # futures history: TWS stitches the continuous series, the gateway reads the front month
    start, end = datetime(2026, 11, 16), datetime(2026, 11, 17)
    await tws.provider.get_historical_prices("ES", "1d", start, end, sec_type="future")
    assert tws.ib.history_calls[-1][0] == "CONTFUT"
    bars = await web.provider.get_historical_prices("ES", "1d", start, end, sec_type="future")
    assert {bar.source_instrument for bar in bars} == {"ESZ6"}
    assert math.isfinite(float(bars[0].close))
