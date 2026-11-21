"""Contract lookup and caches for the Client Portal Gateway."""

import asyncio
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from datetime import time as day_time
from decimal import Decimal
from typing import Any, TypeVar

from pydantic import BaseModel, PositiveInt, TypeAdapter, ValidationError

from app.providers.ibkr_common import (
    FRONT_MONTH_BUFFER,
    FUTURES_EXCHANGES,
    INDEX_EXCHANGES,
    INDEX_ROOT_OVERRIDES,
    select_front_month,
)
from app.providers.ibkr_web_session import IbkrWebSession
from app.utils.errors import DataNotFoundError, DataValidationError, ProviderError

_DAY = 86400
_WEB_INDEX_EXCHANGES = {**INDEX_EXCHANGES, "INDU": "CME"}
_MONTHS = (
    "JAN",
    "FEB",
    "MAR",
    "APR",
    "MAY",
    "JUN",
    "JUL",
    "AUG",
    "SEP",
    "OCT",
    "NOV",
    "DEC",
)
_T = TypeVar("_T")
_Object = dict[str, Any]
_OptionKey = tuple[Decimal, str]


def _redis_backend() -> Any:
    # Import late: app.cache imports the provider registry.
    from app import cache

    return cache._backend


class _ContractCache:
    """Bounded local cache in front of the shared, fail-open Redis connection."""

    def __init__(self, backend: Callable[[], Any]) -> None:
        self._backend = backend
        self._local: OrderedDict[str, tuple[float, bytes]] = OrderedDict()

    def _remember(self, key: str, ttl: int, raw: bytes) -> None:
        if ttl > 0:
            self._local[key] = (time.monotonic() + ttl, raw)
            self._local.move_to_end(key)
            if len(self._local) > 4096:
                self._local.popitem(last=False)

    async def get(self, key: str, adapter: TypeAdapter[_T]) -> _T | None:
        if entry := self._local.get(key):
            if entry[0] > time.monotonic():
                self._local.move_to_end(key)
                return adapter.validate_json(entry[1])
            del self._local[key]
        if (backend := self._backend()) is not None:
            ttl, raw = await backend.get_with_ttl(key)
            if ttl > 0 and raw is not None:
                try:
                    result = adapter.validate_json(raw)
                except ValidationError:
                    return None
                self._remember(key, ttl, raw)
                return result
        return None

    async def put(
        self, key: str, adapter: TypeAdapter[_T], value: _T, ttl: int
    ) -> None:
        if ttl <= 0:
            return
        raw = adapter.dump_json(value)
        self._remember(key, ttl, raw)
        backend = self._backend()
        if backend is not None and time.monotonic() >= backend.retry_at:
            try:
                # Do not apply the public HTTP response cache TTL policy to conids.
                await backend.redis.set(key, raw, ex=ttl)
            except Exception:
                backend.failed()


class WebContract(BaseModel, frozen=True):
    conid: PositiveInt
    symbol: str
    exchange: str
    local_symbol: str | None = None
    name: str | None = None
    currency: str = "USD"

    @property
    def instrument(self) -> str:
        return self.local_symbol or self.symbol

    def source(self, root: str) -> str | None:
        return self.instrument if self.instrument != root else None


_CONTRACT = TypeAdapter(WebContract)
_CONID = TypeAdapter(PositiveInt)
_INFO = TypeAdapter(dict[str, Any])
_STRIKE = TypeAdapter(Decimal)
_STRIKES = TypeAdapter(dict[str, list[Decimal]])
_MISSING = TypeAdapter(bool)
# Strikes without a contract for an expiry (e.g. outside the weekly strike range) are looked up again only after this.
_MISSING_TTL = 6 * 3600
_MISSING_EXPIRY_TTL = 3600
# Concurrent secdef/info lookups for a cold chain; the gateway pacer still bounds the request rate.
_INFO_CONCURRENCY = 4


def stock_root(root: str) -> str:
    """The gateway uses a space for share classes (e.g. BRK B, not BRK.B)."""
    return root.upper().replace(".", " ")


def _date(value: object) -> date | None:
    try:
        return (
            datetime.strptime(str(value), "%Y%m%d").date()
            if len(str(value)) == 8
            else None
        )
    except ValueError:
        return None


def _ttl(day: date) -> int:
    return max(
        0,
        int(
            (
                datetime.combine(day, day_time.min, UTC) - datetime.now(UTC)
            ).total_seconds()
        ),
    )


def _objects(raw: object, endpoint: str) -> list[_Object]:
    if not isinstance(raw, list) or any(not isinstance(row, dict) for row in raw):
        raise ProviderError(
            "Invalid IBKR Web API response shape", details={"endpoint": endpoint}
        )
    return raw


def _conid(row: _Object) -> int:
    try:
        return _CONID.validate_python(row.get("conid"))
    except ValidationError as exc:
        raise ProviderError("Invalid IBKR Web API contract identifier") from exc


def _section(row: _Object, sec_type: str) -> _Object | None:
    sections = row.get("sections") or []
    if not isinstance(sections, list) or any(
        not isinstance(item, dict) for item in sections
    ):
        raise ProviderError("Invalid IBKR Web API security definition sections")
    return next((item for item in sections if item.get("secType") == sec_type), None)


def _month(expiry: date) -> str:
    return f"{_MONTHS[expiry.month - 1]}{expiry.year % 100:02d}"


class IbkrWebContracts:
    def __init__(
        self,
        session: IbkrWebSession,
        *,
        redis_backend: Callable[[], Any] = _redis_backend,
    ) -> None:
        self._session = session
        self._cache = _ContractCache(redis_backend)
        self._search_lock = asyncio.Lock()
        self._option_search: dict[str, tuple[int, WebContract, frozenset[str]]] = {}

    async def resolve(self, root: str, sec_type: str) -> WebContract:
        root = root.upper()
        if sec_type not in {"stock", "etf", "index", "future"}:
            raise DataValidationError(
                f"Unsupported IBKR Web API security type: {sec_type}"
            )
        key = f"mdh:ibkrweb:conid:{sec_type}:{root}"
        if cached := await self._cache.get(key, _CONTRACT):
            return cached
        ttl = 30 * _DAY
        if sec_type == "future":
            contract, last_trade = await self._resolve_future(root)
            ttl = _ttl(last_trade - FRONT_MONTH_BUFFER + timedelta(days=1))
        elif sec_type == "index":
            native = INDEX_ROOT_OVERRIDES.get(root, root)
            exchange = _WEB_INDEX_EXCHANGES.get(native, "CBOE")
            rows = await self._search(native, sec_type="IND")
            match = next(
                (
                    row
                    for row in rows
                    if row.get("symbol") == native
                    and row.get("description") == exchange
                    and _section(row, "IND") is not None
                ),
                None,
            )
            if match is None:
                raise DataNotFoundError("Contract", root)
            contract = WebContract(
                conid=_conid(match),
                symbol=native,
                exchange=exchange,
                name=match.get("companyName"),
            )
        else:
            contract = await self._resolve_stock(stock_root(root))
        await self._cache.put(key, _CONTRACT, contract, ttl)
        return contract

    async def _resolve_stock(self, symbol: str) -> WebContract:
        data = await self._session.request("trsrv/stocks", params={"symbols": symbol})
        if "error" in data:
            raise ProviderError("IBKR Web API stock lookup failed")
        candidates = [
            WebContract(
                conid=_conid(contract),
                symbol=symbol,
                exchange=contract["exchange"],
                name=row.get("name"),
            )
            for row in _objects(data.get(symbol, []), "trsrv/stocks")
            if row.get("assetClass") == "STK"
            for contract in _objects(row.get("contracts"), "trsrv/stocks")
            if contract.get("isUS") is True
        ]
        if not candidates:
            raise DataNotFoundError("Contract", symbol)
        if len(candidates) > 1:
            rows = await self._search(symbol, sec_type="STK")
            valid = {contract.conid: contract for contract in candidates}
            for row in rows:
                if (
                    row.get("symbol") == symbol
                    and _section(row, "STK") is not None
                    and _conid(row) in valid
                ):
                    return valid[_conid(row)]
        return candidates[0]

    async def _resolve_future(self, root: str) -> tuple[WebContract, date]:
        data = await self._session.request("trsrv/futures", params={"symbols": root})
        today = date.today()
        candidates = []
        for row in _objects(data.get(root, []), "trsrv/futures"):
            dates = [
                day
                for field in ("ltd", "expirationDate")
                if (day := _date(row.get(field))) is not None
            ]
            if dates and min(dates) >= today + FRONT_MONTH_BUFFER:
                candidates.append((min(dates), _conid(row)))
        exchange = FUTURES_EXCHANGES.get(root)
        verified = []
        exchanges = set()
        for last_trade, conid in sorted(candidates, key=lambda item: item[0]):
            info = await self.info(conid)
            actual = info.get("exchange")
            if not isinstance(actual, str) or not actual:
                raise ProviderError("Missing IBKR Web API futures exchange")
            if exchange is not None and actual != exchange:
                continue
            exchanges.add(actual)
            contract = WebContract(
                conid=conid,
                symbol=root,
                exchange=actual,
                local_symbol=info.get("local_symbol"),
                name=info.get("company_name"),
                currency=info.get("currency") or "USD",
            )
            verified.append((last_trade, (contract, last_trade)))
            if exchange is not None:
                break
            if len(exchanges) > 1:
                raise DataValidationError(
                    "Unknown futures root must resolve to exactly one exchange",
                    details={"symbol": root, "exchanges": sorted(exchanges)},
                )
        selected = select_front_month(verified, today)
        if selected is None:
            raise DataNotFoundError("Contract", root)
        return selected

    async def info(self, conid: int) -> _Object:
        key = f"mdh:ibkrweb:contract_info:{conid}"
        if cached := await self._cache.get(key, _INFO):
            return cached
        data = await self._session.request(f"iserver/contract/{conid}/info")
        if not data or "error" in data:
            raise ProviderError("Invalid IBKR Web API contract info")
        await self._cache.put(key, _INFO, data, _DAY)
        return data

    async def _search(
        self, symbol: str, *, sec_type: str | None = None, by_name: bool = False
    ) -> list[_Object]:
        path = "iserver/secdef/search"
        params = {"symbol": symbol}
        if sec_type:
            params["secType"] = sec_type
        if by_name:
            params["name"] = "true"
        try:
            data = await self._session.request(
                path, params=params, expected=(dict, list)
            )
        except DataNotFoundError:
            return []
        if isinstance(data, dict) and data.get("error") == "No symbol found":
            return []
        return _objects(data, path)

    async def search_companies(self, query: str) -> list[_Object]:
        async with self._search_lock:
            # name=true may invalidate the server's strike lookup for the same root.
            self._option_search.clear()
            return [
                row
                for row in await self._search(query, by_name=True)
                if row.get("secType") == "STK" or _section(row, "STK") is not None
            ]

    async def _option_underlying(self, root: str) -> tuple[WebContract, frozenset[str]]:
        root = stock_root(root)
        generation = self._session.generation
        cached = self._option_search.get(root)
        if cached is not None and cached[0] == generation:
            return cached[1:]
        # Non-name lookup must take place even if conids already came from Redis.
        rows = await self._search(root)
        candidates = [
            row
            for row in rows
            if row.get("symbol") == root and _section(row, "STK") is not None
        ]
        if not candidates:
            raise DataNotFoundError("Contract", root)
        match = candidates[0]
        if len(candidates) > 1:
            stock = await self.resolve(root, "stock")
            match = next(
                (row for row in candidates if _conid(row) == stock.conid), match
            )
        option = _section(match, "OPT") or {}
        contract = WebContract(
            conid=_conid(match),
            symbol=root,
            exchange=match.get("description") or "SMART",
        )
        months = frozenset(option.get("months", "").split(";")) - {""}
        if len(self._option_search) >= 1024:
            self._option_search.clear()
        self._option_search[root] = (generation, contract, months)
        return contract, months

    async def option_chain(
        self,
        root: str,
        expiry: date,
        lower: Decimal | None,
        upper: Decimal | None,
        rights: Iterable[str],
    ) -> dict[_OptionKey, int]:
        await self._session.ensure_ready()
        async with self._search_lock:
            underlying, months = await self._option_underlying(root)
            if _month(expiry) not in months:
                return {}
            params = {
                "conid": underlying.conid,
                "sectype": "OPT",
                "month": _month(expiry),
                "exchange": "SMART",
            }
            strike_key = f"mdh:ibkrweb:strikes:{underlying.conid}:{_month(expiry)}"
            rows = await self._cache.get(strike_key, _STRIKES)
            if rows is None:
                raw = await self._session.request(
                    "iserver/secdef/strikes", params=params
                )
                try:
                    rows = _STRIKES.validate_python(raw)
                except ValidationError as exc:
                    raise ProviderError("Invalid IBKR Web API strikes payload") from exc
                await self._cache.put(strike_key, _STRIKES, rows, 300)
            keys: list[_OptionKey] = []
            for right in rights:
                values = rows.get("call" if right == "C" else "put")
                if values is None:
                    raise ProviderError("Invalid IBKR Web API strikes payload")
                for strike in values:
                    if (lower is None or lower <= strike) and (
                        upper is None or strike <= upper
                    ):
                        keys.append((strike, right))
            return await self._option_ids(underlying, expiry, sorted(set(keys)))

    async def option_quote(
        self, root: str, expiry: date, strike: Decimal, right: str
    ) -> int | None:
        await self._session.ensure_ready()
        key = (strike, right)
        cached = await self._cache.get(
            self._option_key(stock_root(root), expiry, *key), _CONID
        )
        if cached is not None:
            return cached
        async with self._search_lock:
            underlying, months = await self._option_underlying(root)
            if _month(expiry) not in months:
                return None
            return (await self._option_ids(underlying, expiry, [key])).get(key)

    @staticmethod
    def _option_key(root: str, expiry: date, strike: Decimal, right: str) -> str:
        return f"mdh:ibkrweb:optconid:{root}:{expiry:%Y%m%d}:{right}:{strike.normalize():f}"

    @staticmethod
    def _missing_key(
        root: str, expiry: date, strike: Decimal | None = None, right: str | None = None
    ) -> str:
        suffix = "" if strike is None else f":{right}:{strike.normalize():f}"
        return f"mdh:ibkrweb:optmissing:{root}:{expiry:%Y%m%d}{suffix}"

    async def _option_ids(
        self, underlying: WebContract, expiry: date, keys: list[_OptionKey]
    ) -> dict[_OptionKey, int]:
        root = underlying.symbol
        if keys:
            expiry_missing: bool | None = await self._cache.get(
                self._missing_key(root, expiry), _MISSING
            )
            if expiry_missing:
                return {}
        found: dict[_OptionKey, int] = {}
        missing: dict[Decimal, set[str]] = {}
        for strike, right in keys:
            if (
                conid := await self._cache.get(
                    self._option_key(root, expiry, strike, right), _CONID
                )
            ) is not None:
                found[strike, right] = conid
            elif not await self._cache.get(
                self._missing_key(root, expiry, strike, right), _MISSING
            ):
                missing.setdefault(strike, set()).add(right)
        ttl = _ttl(expiry + timedelta(days=1))
        path = "iserver/secdef/info"
        limit = asyncio.Semaphore(_INFO_CONCURRENCY)

        async def lookup(strike: Decimal, rights: set[str]) -> list[_Object]:
            params: dict[str, Any] = {
                "conid": underlying.conid,
                "sectype": "OPT",
                "month": _month(expiry),
                "strike": f"{strike:f}",
                "exchange": "SMART",
            }
            if len(rights) == 1:
                params["right"] = next(iter(rights))
            async with limit:
                try:
                    return _objects(
                        await self._session.request(path, params=params, expected=list),
                        path,
                    )
                except (DataNotFoundError, DataValidationError):
                    return []  # the gateway rejects strikes it does not list; skip only this strike

        # A TaskGroup cancels the remaining lookups as soon as one fails with a real error.
        async with asyncio.TaskGroup() as group:
            tasks = {
                strike: group.create_task(lookup(strike, rights))
                for strike, rights in missing.items()
            }
        for strike, rights in missing.items():
            rows = tasks[strike].result()
            # Prefer the standard trading class to adjusted contracts with the same strike.
            rows.sort(key=lambda row: row.get("tradingClass") != root)
            for row in rows:
                side = row.get("right")
                if (
                    not isinstance(side, str)
                    or side not in rights
                    or _date(row.get("maturityDate")) != expiry
                ):
                    continue
                try:
                    actual_strike = _STRIKE.validate_python(row.get("strike"))
                except ValidationError as exc:
                    raise ProviderError("Invalid IBKR Web API option strike") from exc
                if actual_strike == strike and (strike, side) not in found:
                    conid = _conid(row)
                    found[strike, side] = conid
                    await self._cache.put(
                        self._option_key(root, expiry, strike, side), _CONID, conid, ttl
                    )
            for side in rights:
                if (strike, side) not in found:
                    await self._cache.put(
                        self._missing_key(root, expiry, strike, side),
                        _MISSING,
                        True,
                        _MISSING_TTL,
                    )
        if missing and not found:
            # The month is listed but this expiry is not: answer repeated requests without a strike walk.
            await self._cache.put(
                self._missing_key(root, expiry), _MISSING, True, _MISSING_EXPIRY_TTL
            )
        return {key: found[key] for key in keys if key in found}
