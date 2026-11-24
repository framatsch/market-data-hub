"""Market-data provider for the browser-authenticated IBKR Client Portal Gateway."""

from datetime import UTC, date, datetime, tzinfo
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfoNotFoundError

from app.config import settings
from app.models.company import CompanyProfile, CompanySummary
from app.models.options import OptionChain, OptionQuote
from app.models.price import PriceBar, PriceQuote
from app.models.volatility import (
    ImpliedVolatilityTenor,
    VolatilityHistory,
    VolatilitySecType,
    VolatilitySnapshot,
    VolatilityTenorDays,
    quantize_iv,
)
from app.providers.base import (
    BaseCompanyProvider,
    BaseOptionsProvider,
    BasePriceProvider,
    BaseVolatilityProvider,
)
from app.providers.ibkr_common import (
    NATIVE_INTERVALS,
    exchange_timezone,
    format_occ_symbol,
    in_trading_session,
    parse_occ_symbol,
)
from app.providers.ibkr_web_config import IbkrWebConnectionConfig
from app.providers.ibkr_web_contracts import IbkrWebContracts, WebContract, stock_root
from app.providers.ibkr_web_marketdata import (
    HISTORY_WINDOWS,
    OPTION_FIELDS,
    QUOTE_FIELDS,
    SnapshotEngine,
    WebHistory,
    availability,
    entitlement_error,
    number,
    percentage,
    price,
    quantity,
    timestamp_ms,
)
from app.providers.ibkr_web_session import PROVIDER, IbkrWebSession
from app.utils.errors import (
    AppError,
    CapabilityNotSupportedError,
    DataNotFoundError,
    DataValidationError,
    ProviderError,
)
from app.utils.symbols import canonical_symbol

_CENTRAL_EXCHANGES = {"CME", "CBOT", "ECBOT", "CFE"}
_Payload = dict[str, Any]


class IbkrWebProvider(
    BasePriceProvider, BaseCompanyProvider, BaseOptionsProvider, BaseVolatilityProvider
):
    name = PROVIDER
    native_intervals = frozenset(NATIVE_INTERVALS)
    price_sec_types = frozenset({"stock", "etf", "index", "future"})
    price_history_sec_types = price_sec_types
    volatility_sec_types = price_sec_types
    volatility_history_sec_types: frozenset[str] = frozenset()
    volatility_tenors = frozenset({30})
    option_underlying_sec_types = frozenset({"stock", "etf", "future"})

    def __init__(self, *, session: IbkrWebSession | None = None) -> None:
        self._runtime_config: Any = None
        self._gateway = session
        self._contract_resolver: IbkrWebContracts | None = None
        self._schedule_cache: dict[int, tuple[tzinfo, date, _Payload]] = {}
        self._snapshot_engine: SnapshotEngine | None = None
        self._history_reader: WebHistory | None = None

    @staticmethod
    def _transport_settings(
        config: Any,
    ) -> tuple[IbkrWebConnectionConfig, float, float]:
        return (
            IbkrWebConnectionConfig.from_settings(
                getattr(config, "connection_config", None)
            ),
            getattr(config, "timeout_seconds", settings.PROVIDER_REQUEST_TIMEOUT),
            getattr(config, "rate_limit_per_sec", 6.0),
        )

    def requires_replacement(self, config: Any) -> bool:
        return self._gateway is not None and self._transport_settings(
            self._runtime_config
        ) != self._transport_settings(config)

    def configure(self, config: Any) -> None:
        if self.requires_replacement(config):
            raise RuntimeError(
                "Replace the IBKR Web API provider when its gateway settings change"
            )
        super().configure(config)

    @property
    def session(self) -> IbkrWebSession:
        if self._gateway is None:
            config, timeout, rate = self._transport_settings(self._runtime_config)
            self._gateway = IbkrWebSession(config, timeout=timeout, rate=rate)
        return self._gateway

    @property
    def contracts(self) -> IbkrWebContracts:
        if self._contract_resolver is None:
            self._contract_resolver = IbkrWebContracts(self.session)
        return self._contract_resolver

    @property
    def snapshots(self) -> SnapshotEngine:
        if self._snapshot_engine is None:
            self._snapshot_engine = SnapshotEngine(
                self.session, self.session.config.max_streams
            )
        return self._snapshot_engine

    @property
    def history(self) -> WebHistory:
        if self._history_reader is None:
            self._history_reader = WebHistory(self.session)
        return self._history_reader

    def start(self) -> None:
        self.session.start()

    async def close(self) -> None:
        if self._gateway is not None:
            await self._gateway.close()

    async def test_connection(self) -> dict[str, Any]:
        return await self.session.test_connection()

    def _market_data_type(self, value: int | None) -> int:
        value = self.session.config.market_data_type if value is None else value
        if type(value) is not int or value not in (1, 2, 3, 4):
            raise DataValidationError("market_data_type must be between 1 and 4")
        return value

    @staticmethod
    def _default_zone(contract: WebContract) -> tzinfo:
        return exchange_timezone(
            "US/Central" if contract.exchange in _CENTRAL_EXCHANGES else "US/Eastern"
        )

    async def _schedule(self, contract: WebContract) -> tuple[tzinfo, _Payload] | None:
        cached = self._schedule_cache.get(contract.conid)
        now = datetime.now(UTC)
        if cached is not None and now.astimezone(cached[0]).date() == cached[1]:
            return cached[0], cached[2]
        try:
            body = await self.session.request(
                "contract/trading-schedule", params={"conid": contract.conid}
            )
            zone = exchange_timezone(body["exchange_time_zone"])
            schedules = body["schedules"]
            if not isinstance(schedules, dict):
                return None
        except (AppError, KeyError, ValueError, TypeError, ZoneInfoNotFoundError):
            return None
        if len(self._schedule_cache) >= 1024:
            self._schedule_cache.clear()
        self._schedule_cache[contract.conid] = (
            zone,
            now.astimezone(zone).date(),
            schedules,
        )
        return zone, schedules

    async def _market_open(self, contract: WebContract) -> bool | None:
        result = await self._schedule(contract)
        if result is None:
            return None
        zone, schedules = result
        now = datetime.now(UTC)
        today = now.astimezone(zone).strftime("%Y%m%d")
        if today not in schedules:
            return False
        try:
            for hours in schedules[today]["extended_hours"]:
                opening = datetime.fromtimestamp(hours["opening"], UTC)
                closing = datetime.fromtimestamp(hours["closing"], UTC)
                if in_trading_session(now, opening, closing):
                    return True
            return False
        except (KeyError, ValueError, TypeError, OverflowError, OSError):
            return None

    async def get_last_price(
        self, symbol: str, market_data_type: int | None = None, sec_type: str = "stock"
    ) -> PriceQuote:
        effective = self._market_data_type(market_data_type)
        root = symbol.upper()
        contract = await self.contracts.resolve(root, sec_type)
        snapshots = await self.snapshots.get(
            [contract.conid],
            QUOTE_FIELDS,
            timeout=settings.IBKRWEB_SNAPSHOT_TIMEOUT_SECONDS,
            complete=lambda row: (
                bool(availability(row.get("6509")))
                and (
                    price(row) is not None
                    or availability(row.get("6509")) in {"N", "O"}
                )
            ),
        )
        row = snapshots.get(contract.conid, {})
        current = price(row)
        code = availability(row.get("6509"))
        denied = entitlement_error(
            row.get("6509"),
            root,
            sec_type,
            contract.instrument,
            market_data_type=effective
            if code or effective == 1 or current is not None
            else None,
        )
        if denied and (
            code == "O"
            or effective == 1
            or not settings.IBKR_FALLBACK_ON_SUBSCRIPTION_ERROR
        ):
            raise denied
        if current is None or denied is not None:
            try:
                fallback = await self.history.last_daily(contract, root, sec_type)
            except AppError:
                if denied:
                    raise denied from None  # like ibkr: a known denial outranks a failed fallback
                raise
            if fallback is None:
                if denied:
                    raise denied
                raise DataNotFoundError("MarketData", canonical_symbol(root, sec_type))
            stamp, bar = fallback
            return PriceQuote(
                symbol=canonical_symbol(root, sec_type),
                price=bar.close,
                currency=contract.currency,
                timestamp=stamp,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                volume=bar.volume,
                provider=self.name,
                is_market_open=await self._market_open(contract),
                source_instrument=contract.source(root),
            )
        return PriceQuote(
            symbol=canonical_symbol(root, sec_type),
            price=current,
            currency=contract.currency,
            timestamp=timestamp_ms(row.get("_updated")) or datetime.now(UTC),
            bid=price(row, ("84",)),
            ask=price(row, ("86",)),
            open=price(row, ("7295",)),
            high=price(row, ("70",)),
            low=price(row, ("71",)),
            volume=quantity(row.get("7762"), fallback=row.get("87")),
            provider=self.name,
            is_market_open=await self._market_open(contract),
            source_instrument=contract.source(root),
        )

    async def get_historical_prices(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
        extended_hours: bool = False,
        sec_type: str = "stock",
    ) -> list[PriceBar]:
        if interval not in HISTORY_WINDOWS:
            raise ProviderError(
                f"Unsupported interval '{interval}' for IBKR Web API provider.",
                details={"supported_intervals": list(NATIVE_INTERVALS)},
            )
        root = symbol.upper()
        contract = await self.contracts.resolve(root, sec_type)
        return await self.history.bars(
            contract,
            root,
            sec_type,
            interval,
            start,
            end,
            extended_hours,
            self._default_zone(contract),
        )

    @staticmethod
    def _has_option_price(row: _Payload) -> bool:
        return price(row, ("31", "7296", "84", "86")) is not None

    async def _option_snapshots(
        self, conids: list[int], *, fraction: float, underlying_conid: int | None = None
    ) -> dict[int, _Payload]:
        def complete(row: _Payload) -> bool:
            if not availability(row.get("6509")):
                return False
            if underlying_conid is not None and row.get("conid") == underlying_conid:
                return price(row, ("31", "7296")) is not None
            return self._has_option_price(row)

        return await self.snapshots.get(
            conids,
            OPTION_FIELDS,
            timeout=settings.IBKRWEB_OPTION_SNAPSHOT_TIMEOUT_SECONDS,
            required_fraction=fraction,
            complete=complete,
            terminal=lambda row: availability(row.get("6509")) in {"N", "O"},
            required_conid=underlying_conid,
        )

    @staticmethod
    def _option_model(
        root: str,
        expiry: date,
        strike: Decimal,
        right: str,
        row: _Payload,
        *,
        local_symbol: str | None = None,
    ) -> OptionQuote:
        identifier = local_symbol or format_occ_symbol(
            stock_root(root), expiry, right, strike
        )
        return OptionQuote(
            symbol=identifier,
            underlying_symbol=root,
            strike=strike,
            expiry=expiry,
            type="call" if right == "C" else "put",
            price=price(row, ("31", "7296")) or Decimal(0),
            bid=price(row, ("84",)),
            ask=price(row, ("86",)),
            volume=quantity(row.get("7762"), fallback=row.get("87")) or 0,
            open_interest=quantity(row.get("7638")),
            implied_volatility=_float(percentage(row.get("7633"))),
            delta=_float(number(row.get("7308"))),
            gamma=_float(number(row.get("7309"))),
            theta=_float(number(row.get("7310"))),
            vega=_float(number(row.get("7311"))),
            provider=PROVIDER,
        )

    async def get_option_chain(
        self,
        symbol: str,
        expiry: date,
        min_strike: Decimal | None = None,
        max_strike: Decimal | None = None,
        right: Literal["call", "put"] | None = None,
        market_data_type: int | None = None,
        *,
        sec_type: str = "stock",
        trading_class: str | None = None,
    ) -> OptionChain:
        effective = self._market_data_type(market_data_type)
        root = symbol.upper()
        rights = ("C", "P") if right is None else ("C" if right == "call" else "P",)
        canonical = canonical_symbol(root, sec_type)
        terms = None
        underlying_conid = None
        underlying_symbol = None
        if sec_type == "future":
            terms, contracts = await self.contracts.futures_option_chain(
                root, expiry, min_strike, max_strike, rights, trading_class
            )
            rows: list[tuple[Decimal, str, int, str | None]] = [
                (listing.strike, listing.right, identity.conid, identity.local_symbol)
                for listing, identity in contracts
            ]
            underlying_ids = {
                identity.underlying_conid
                for _, identity in contracts
                if identity.underlying_conid is not None
            }
            if len(underlying_ids) > 1:
                raise ProviderError(
                    "Inconsistent IBKR Web API futures option underlyings"
                )
            underlying_conid = next(iter(underlying_ids), None)
            if underlying_conid is not None:
                info = await self.contracts.info(underlying_conid)
                underlying_symbol = info.get("local_symbol") or None
        else:
            ids = await self.contracts.option_chain(
                root, expiry, min_strike, max_strike, rights
            )
            rows = [
                (strike, side, conid, None) for (strike, side), conid in ids.items()
            ]

        conids = [conid for _, _, conid, _ in rows]
        if underlying_conid is not None:
            conids.insert(0, underlying_conid)
        snapshots = await self._option_snapshots(
            conids, fraction=0.5, underlying_conid=underlying_conid
        )
        options = []
        usable = 0
        denial = None
        for strike, side, conid, local_symbol in rows:
            row = snapshots.get(conid, {})
            code = availability(row.get("6509"))
            denied = entitlement_error(
                row.get("6509"),
                root,
                sec_type,
                local_symbol or str(conid),
                market_data_type=effective
                if code or self._has_option_price(row)
                else None,
            )
            if denied is not None:
                if code == "O":
                    raise denied
                denial = denied
                row = {}
            elif self._has_option_price(row):
                usable += 1
            options.append(
                self._option_model(
                    canonical, expiry, strike, side, row, local_symbol=local_symbol
                )
            )
        if denial is not None and not usable:
            raise denial
        if terms is not None:
            underlying_row = (
                snapshots.get(underlying_conid, {})
                if underlying_conid is not None
                else {}
            )
            code = availability(underlying_row.get("6509"))
            underlying_price = price(underlying_row, ("31", "7296"))
            if code and entitlement_error(
                code,
                root,
                sec_type,
                underlying_symbol or root,
                market_data_type=effective,
            ):
                underlying_price = None
            return terms.chain(
                root,
                expiry,
                self.name,
                options,
                underlying_contract=underlying_symbol,
                underlying_price=underlying_price,
            )
        return OptionChain(
            underlying_symbol=canonical,
            expiry=expiry,
            options=options,
            provider=self.name,
        )

    async def get_option_quote(
        self, symbol: str, option_id: str, market_data_type: int | None = None
    ) -> OptionQuote:
        try:
            root, expiry, right, strike = parse_occ_symbol(option_id)
        except ValueError as exc:
            raise DataNotFoundError("OptionContract", option_id) from exc
        symbol = symbol.upper()
        if root != stock_root(symbol):
            raise DataNotFoundError("OptionContract", option_id)
        effective = self._market_data_type(market_data_type)
        conid = await self.contracts.option_quote(root, expiry, strike, right)
        if conid is None:
            raise DataNotFoundError("OptionContract", option_id)
        row = (await self._option_snapshots([conid], fraction=1)).get(conid, {})
        if error := entitlement_error(
            row.get("6509"),
            root,
            "stock",
            option_id,
            market_data_type=effective
            if availability(row.get("6509")) or self._has_option_price(row)
            else None,
        ):
            raise error
        if not self._has_option_price(row):
            raise DataNotFoundError("MarketData", option_id)
        return self._option_model(symbol, expiry, strike, right, row)

    async def get_implied_volatility(
        self,
        symbol: str,
        sec_type: VolatilitySecType = "stock",
        ric: str | None = None,
    ) -> VolatilitySnapshot:
        if ric is not None:
            raise DataValidationError("The ric override is only supported by LSEG")
        root = symbol.upper()
        contract = await self.contracts.resolve(root, sec_type)
        rows = await self.snapshots.get(
            [contract.conid],
            "7283,6509",
            timeout=settings.IBKRWEB_IV_TIMEOUT_SECONDS,
            complete=lambda row: (
                quantize_iv(percentage(row.get("7283"))) is not None
                or availability(row.get("6509")) in {"N", "O"}
            ),
        )
        row = rows.get(contract.conid, {})
        if error := entitlement_error(
            row.get("6509"), root, sec_type, contract.instrument
        ):
            raise error
        iv = quantize_iv(percentage(row.get("7283")))
        if iv is None:
            raise DataNotFoundError(
                "ImpliedVolatility", root, details={"reason": "no_iv_data"}
            )
        info = await self.contracts.info(contract.conid)
        stamp = timestamp_ms(row.get("_updated"))
        return VolatilitySnapshot(
            symbol=canonical_symbol(root, sec_type),
            sec_type=sec_type,
            method="provider_model_30d",
            source_instrument=info.get("local_symbol") or contract.instrument,
            underlying=contract.symbol,
            underlying_name=info.get("company_name") or contract.name,
            market=contract.exchange,
            as_of=stamp.astimezone(self._default_zone(contract)).date()
            if stamp
            else None,
            implied=[ImpliedVolatilityTenor(tenor_days=30, iv=iv)],
            provider=self.name,
        )

    async def get_implied_volatility_history(
        self,
        symbol: str,
        start: date,
        end: date,
        tenor_days: VolatilityTenorDays = 30,
        sec_type: VolatilitySecType = "stock",
        ric: str | None = None,
    ) -> VolatilityHistory:
        if ric is not None:
            raise DataValidationError("The ric override is only supported by LSEG")
        raise CapabilityNotSupportedError(
            self.name, "history", sec_type=sec_type, tenor_days=tenor_days, supported=[]
        )

    async def get_company_profile(self, symbol: str) -> CompanyProfile:
        root = symbol.upper()
        contract = await self.contracts.resolve(root, "stock")
        info = await self.contracts.info(contract.conid)
        return CompanyProfile(
            symbol=root,
            name=info.get("company_name") or contract.name or root,
            exchange=contract.exchange,
            currency=info.get("currency") or contract.currency,
            industry=info.get("industry"),
            sector=info.get("category"),
            provider=self.name,
        )

    async def search_companies(self, query: str) -> list[CompanySummary]:
        rows = await self.contracts.search_companies(query)
        companies = []
        for row in rows:
            symbol = row.get("symbol")
            if not isinstance(symbol, str) or not symbol:
                continue
            header = row.get("companyHeader") or ""
            label, separator, exchange = header.removesuffix(")").rpartition(" (")
            companies.append(
                CompanySummary(
                    symbol=symbol,
                    name=row.get("companyName") or label or header or symbol,
                    exchange=row.get("description")
                    or (exchange if separator else "SMART"),
                    provider=self.name,
                )
            )
        return companies


def _float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None
