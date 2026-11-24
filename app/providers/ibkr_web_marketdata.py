"""Gateway snapshot polling, market-data entitlements and historical bars."""

import asyncio
import math
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta, tzinfo
from datetime import time as day_time
from decimal import Decimal, InvalidOperation
from typing import Any

from app.config import settings
from app.models.price import PriceBar
from app.providers.ibkr_common import NATIVE_INTERVALS
from app.providers.ibkr_web_contracts import WebContract
from app.providers.ibkr_web_session import PROVIDER, IbkrWebSession
from app.utils.errors import (
    DataValidationError,
    ProviderError,
    ProviderNotEntitledError,
)
from app.utils.symbols import canonical_symbol

_SNAPSHOT = "iserver/marketdata/snapshot"
_HISTORY = "iserver/marketdata/history"
_Row = dict[str, Any]
_MAGNITUDES = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
_TYPES = {1: "R", 2: "RZ", 3: "RDZY", 4: "RDZY"}
# Pairs were accepted by CPGW with outsideRth=true. Each full period is
# conservatively <= 1,000 bars even with around-the-clock trades.
HISTORY_WINDOWS = {
    "1m": ("1min", "12h", timedelta(minutes=1)),
    "2m": ("2min", "1d", timedelta(minutes=2)),
    "5m": ("5min", "3d", timedelta(minutes=5)),
    "15m": ("15min", "1w", timedelta(minutes=15)),
    "30m": ("30min", "2w", timedelta(minutes=30)),
    "1h": ("1h", "1m", timedelta(hours=1)),
    "1d": ("1d", "2y", timedelta(days=1)),
    "1w": ("1w", "10y", timedelta(weeks=1)),
}
# Calendar span of one window; used to bound how many history requests one call may spend
# (the gateway allows 50 history requests per minute, shared with last-price fallbacks).
_WINDOW_SPANS = {
    "12h": timedelta(hours=12),
    "1d": timedelta(days=1),
    "3d": timedelta(days=3),
    "1w": timedelta(weeks=1),
    "2w": timedelta(weeks=2),
    "1m": timedelta(days=30),
    "2y": timedelta(days=730),
    "10y": timedelta(days=3650),
}
MAX_HISTORY_WINDOWS = 40
QUOTE_FIELDS = "31,84,86,87,7762,70,71,7295,7296,7741,6509"
OPTION_FIELDS = "31,84,86,87,7762,7296,7633,7308,7309,7310,7311,7638,6509"


def number(
    value: object, *, last: bool = False, compact: bool = False
) -> Decimal | None:
    if not isinstance(value, (str, int, float, Decimal)) or isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", "")
    if last and text[:1] in {"C", "H"}:
        text = text[1:].strip()
    multiplier = _MAGNITUDES.get(text[-1:].upper(), 1) if compact else 1
    if multiplier != 1:
        text = text[:-1]
    try:
        parsed = Decimal(text)
        return parsed * multiplier if parsed.is_finite() else None
    except InvalidOperation:
        return None


def percentage(value: object) -> Decimal | None:
    if isinstance(value, str):
        value = value.strip().removesuffix("%")
    result = number(value)
    return result / 100 if result is not None and result >= 0 else None


def quantity(value: object, *, fallback: object = None) -> int | None:
    result = number(value, compact=True)
    if result is None:
        result = number(fallback, compact=True)
    return int(result) if result is not None and result >= 0 else None


def price(row: _Row, fields: Sequence[str] = ("31", "7296", "7741")) -> Decimal | None:
    for field in fields:
        value = number(row.get(field), last=field == "31")
        if (
            value is not None and value != -1
        ):  # IBKR sentinel (negative futures prices remain valid)
            return value
    return None


def timestamp_ms(value: object) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, UTC)
    except (ValueError, OverflowError, OSError):
        return None


def availability(value: object) -> str:
    return value[:1] if isinstance(value, str) else ""


def entitlement_error(
    value: object,
    root: str,
    sec_type: str,
    instrument: str,
    *,
    market_data_type: int | None = None,
) -> ProviderNotEntitledError | None:
    code = availability(value)
    if code == "O":
        hint = "Complete the Market Data API Acknowledgement in IBKR Client Portal settings."
    elif code == "N":
        hint = "The IBKR account is not subscribed to market data for this instrument."
    elif market_data_type is not None and (
        not code or code not in _TYPES[market_data_type]
    ):
        hint = (
            "Live data needs a market data subscription."
            if market_data_type == 1
            else "The gateway returned a different market data type."
        )
    else:
        return None
    return ProviderNotEntitledError(
        PROVIDER,
        symbol=canonical_symbol(root, sec_type),
        instrument=instrument,
        details={"availability": value, "hint": hint, "sec_type": sec_type},
    )


class SnapshotEngine:
    """Snapshot polling with a bounded number of open gateway streams.

    Polls run concurrently. Only the stream bookkeeping is serialised, and ``unsubscribeall``
    is sent only once no poll is active, so it never interrupts another request's poll.
    """

    def __init__(self, session: IbkrWebSession, max_streams: int) -> None:
        self._session = session
        self._max_streams = max_streams
        self._streams: set[int] = set()
        self._generation = -1
        self._active = 0
        self._draining = False
        self._condition = asyncio.Condition()

    async def get(
        self,
        conids: Sequence[int],
        fields: str,
        *,
        timeout: float,
        complete: Callable[[_Row], bool],
        required_fraction: float = 1,
        terminal: Callable[[_Row], bool] | None = None,
        required_conid: int | None = None,
    ) -> dict[int, _Row]:
        size = min(settings.IBKRWEB_SNAPSHOT_BATCH_SIZE, self._max_streams)
        unique = list(dict.fromkeys(conids))
        result: dict[int, _Row] = {}
        for i in range(0, len(unique), size):
            batch = unique[i : i + size]
            await self._session.ensure_ready()
            await self._reserve(batch)
            try:
                result.update(
                    await self._poll(
                        batch,
                        fields,
                        timeout,
                        complete,
                        required_fraction,
                        terminal,
                        required_conid if required_conid in batch else None,
                    )
                )
            finally:
                async with self._condition:
                    self._active -= 1
                    self._condition.notify_all()
        return result

    async def _reserve(self, batch: list[int]) -> None:
        async with self._condition:
            while True:
                if self._generation != self._session.generation:
                    if self._streams:
                        # After a brokerage re-initialisation the open streams are unknown: reset them.
                        self._draining = True
                    else:
                        self._generation = self._session.generation
                if (
                    not self._draining
                    and len(self._streams.union(batch)) <= self._max_streams
                ):
                    break
                self._draining = True  # stop new polls so that the budget can be reset
                if self._active == 0:
                    try:
                        await self._session.request("iserver/marketdata/unsubscribeall")
                    finally:
                        self._draining = False
                        self._condition.notify_all()
                    self._streams.clear()
                    self._generation = self._session.generation
                    break
                await self._condition.wait()
            # A request might open streams even if its response is lost or times out.
            self._streams.update(batch)
            self._active += 1

    async def _poll(
        self,
        batch: list[int],
        fields: str,
        timeout: float,
        complete: Callable[[_Row], bool],
        required_fraction: float,
        terminal: Callable[[_Row], bool] | None,
        required_conid: int | None,
    ) -> dict[int, _Row]:
        params = {"conids": ",".join(map(str, batch)), "fields": fields}
        latest: dict[int, _Row] = {}
        included = set(batch)
        try:
            async with asyncio.timeout(timeout):
                while True:
                    raw = await self._session.request(
                        _SNAPSHOT, params=params, expected=list
                    )
                    for row in raw:
                        if not isinstance(row, dict):
                            raise ProviderError("Invalid IBKR Web API snapshot entry")
                        conid = row.get("conid")
                        if type(conid) is int and conid in included:
                            latest.setdefault(conid, {}).update(row)
                    filled = sum(
                        complete(row)
                        for conid, row in latest.items()
                        if conid != required_conid
                    )
                    required = (
                        latest.get(required_conid, {})
                        if required_conid is not None
                        else {}
                    )
                    required_ready = (
                        required_conid is None
                        or complete(required)
                        or (terminal is not None and terminal(required))
                    )
                    target = len(batch) - (required_conid is not None)
                    if (required_ready and filled >= target * required_fraction) or (
                        terminal is not None
                        and len(latest) == len(batch)
                        and all(
                            complete(row) or terminal(row) for row in latest.values()
                        )
                    ):
                        break
                    await asyncio.sleep(0.5)
        except TimeoutError:
            pass  # return the values already collected, if any
        return latest


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class WebHistory:
    def __init__(self, session: IbkrWebSession) -> None:
        self._session = session

    async def _page(
        self,
        contract: WebContract,
        root: str,
        sec_type: str,
        *,
        bar: str,
        period: str,
        extended: bool,
        cursor: datetime | None = None,
    ) -> tuple[list[tuple[datetime, _Row]], Decimal]:
        params: _Row = {
            "conid": contract.conid,
            "period": period,
            "bar": bar,
            "outsideRth": str(extended).lower(),
            "source": "Last",
        }
        if cursor is not None:
            params.update(startTime=cursor.strftime("%Y%m%d-%H:%M:%S"), direction=-1)
        data = await self._session.request(_HISTORY, params=params)
        if error := entitlement_error(
            data.get("mdAvailability"), root, sec_type, contract.instrument
        ):
            raise error
        rows = data.get("data")
        if not isinstance(rows, list):
            raise ProviderError("Invalid IBKR Web API history payload")
        parsed = []
        for row in rows:
            stamp = timestamp_ms(row.get("t")) if isinstance(row, dict) else None
            if stamp is None:
                raise ProviderError("Invalid IBKR Web API bar timestamp")
            parsed.append((stamp, row))
        factor = (
            number(data.get("volumeFactor")) if "volumeFactor" in data else Decimal(1)
        )
        if factor is None or factor <= 0:
            raise ProviderError("Invalid IBKR Web API volume factor")
        return parsed, factor

    async def last_daily(
        self,
        contract: WebContract,
        root: str,
        sec_type: str,
    ) -> tuple[datetime, PriceBar] | None:
        rows, factor = await self._page(
            contract, root, sec_type, bar="1d", period="1w", extended=False
        )
        if not rows:
            return None
        stamp, row = max(rows, key=lambda pair: pair[0])
        return stamp, self._bar(contract, root, sec_type, stamp, row, factor)

    async def bars(
        self,
        contract: WebContract,
        root: str,
        sec_type: str,
        interval: str,
        start: datetime,
        end: datetime,
        extended: bool,
        zone: tzinfo,
    ) -> list[PriceBar]:
        try:
            bar, period, step = HISTORY_WINDOWS[interval]
        except KeyError as exc:
            raise ProviderError(
                f"Unsupported interval '{interval}' for IBKR Web API provider.",
                details={"supported_intervals": list(NATIVE_INTERVALS)},
            ) from exc
        start, end = _utc(start), _utc(end)
        if start > end:
            return []
        windows = (
            math.ceil((min(end, datetime.now(UTC)) - start) / _WINDOW_SPANS[period]) + 1
        )
        if windows > MAX_HISTORY_WINDOWS:
            raise DataValidationError(
                f"Requested range is too long for interval '{interval}' on the IBKR Web API provider.",
                details={
                    "interval": interval,
                    "max_span_days": (
                        _WINDOW_SPANS[period] * (MAX_HISTORY_WINDOWS - 1)
                    ).days,
                },
            )
        is_calendar_bar = interval in {"1d", "1w"}
        # Include the session containing the range end. The gateway treated
        # startTime as exclusive and sometimes omitted the adjacent minute.
        offset = timedelta(days=1) if is_calendar_bar else step * 2
        cursor = min(end + offset, datetime.now(UTC))
        collected: dict[datetime, PriceBar] = {}
        # Overlapping windows need some slack over the estimate, but the walk is never unbounded.
        for _ in range(windows + MAX_HISTORY_WINDOWS // 4):
            if cursor < start:
                break
            rows, factor = await self._page(
                contract,
                root,
                sec_type,
                bar=bar,
                period=period,
                extended=extended,
                cursor=cursor,
            )
            if not rows:
                break
            for stamp, row in rows:
                normalized = stamp
                if interval == "1d":
                    normalized = datetime.combine(
                        stamp.astimezone(zone).date(), day_time.min
                    )
                elif interval == "1w":
                    normalized = datetime.combine(stamp.date(), day_time.min)
                if start <= _utc(normalized) <= end and stamp not in collected:
                    collected[stamp] = self._bar(
                        contract, root, sec_type, normalized, row, factor
                    )
            earliest = min(stamp for stamp, _ in rows)
            if is_calendar_bar:
                earliest_day = (
                    earliest.astimezone(zone).date()
                    if interval == "1d"
                    else earliest.date()
                )
                covers_start = earliest_day <= start.date()
            else:
                covers_start = earliest <= start
            if covers_start or earliest >= cursor:
                break
            # Overlap, then de-duplicate, to avoid holes at exclusive bounds.
            candidate = earliest + (timedelta(days=1) if is_calendar_bar else step * 2)
            cursor = candidate if candidate < cursor else earliest
        else:
            raise ProviderError(
                "IBKR Web API history did not cover the requested range",
                details={"interval": interval},
            )
        return [collected[stamp] for stamp in sorted(collected)]

    @staticmethod
    def _bar(
        contract: WebContract,
        root: str,
        sec_type: str,
        stamp: datetime,
        row: _Row,
        factor: Decimal,
    ) -> PriceBar:
        opening, high, low, close = (
            number(row.get(field)) for field in ("o", "h", "l", "c")
        )
        if opening is None or high is None or low is None or close is None:
            raise ProviderError("Invalid IBKR Web API history price")
        volume = number(row.get("v"))
        return PriceBar(
            symbol=canonical_symbol(root, sec_type),
            start=stamp,
            end=stamp,
            open=opening,
            high=high,
            low=low,
            close=close,
            volume=int((volume or Decimal(0)) * factor),
            provider=PROVIDER,
            source_instrument=contract.source(root),
        )
