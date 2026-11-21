"""Transport-independent instrument conventions shared by the IBKR providers."""

import re
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TypeVar
from zoneinfo import ZoneInfo

FUTURES_EXCHANGES = {
    **dict.fromkeys(("ES", "NQ", "RTY"), "CME"),
    **dict.fromkeys(("YM", "ZC", "ZW", "ZS", "ZN", "ZB"), "CBOT"),
    **dict.fromkeys(("CL", "NG", "RB", "HO"), "NYMEX"),
    **dict.fromkeys(("GC", "SI", "HG"), "COMEX"),
}
INDEX_ROOT_OVERRIDES = {"DJI": "INDU"}
INDEX_EXCHANGES = {
    "SPX": "CBOE",
    "RUT": "RUSSELL",
    "VIX": "CBOE",
    "NDX": "NASDAQ",
    "DJX": "CBOE",
    "INDU": "NYSE",
}
NATIVE_INTERVALS = ("1m", "2m", "5m", "15m", "30m", "1h", "1d", "1w")
FRONT_MONTH_BUFFER = timedelta(days=7)

_EXCHANGE_TIMEZONE_NAMES = {
    "US/Eastern": "America/New_York",
    "MET": "Europe/Berlin",
    "Japan": "Asia/Tokyo",
    "US/Central": "America/Chicago",
    "US/Mountain": "America/Denver",
    "US/Pacific": "America/Los_Angeles",
}
_OCC_ROOT = re.compile(r"[A-Z0-9]+(?: [A-Z0-9]+)?", re.ASCII)
_OCC_SYMBOL = re.compile(r"([A-Z0-9 ]{6})([0-9]{6})([CP])([0-9]{8})", re.ASCII)
_Contract = TypeVar("_Contract")
_Boundary = TypeVar("_Boundary", str, datetime)


def select_front_month(
    contracts: Iterable[tuple[date, _Contract]], as_of: date
) -> _Contract | None:
    """Return the earliest eligible contract, preserving input order for ties."""
    cutoff = as_of + FRONT_MONTH_BUFFER
    selected = min(
        (item for item in contracts if item[0] >= cutoff),
        key=lambda item: item[0],
        default=None,
    )
    return selected[1] if selected is not None else None


def exchange_timezone(timezone_id: str = "US/Eastern") -> ZoneInfo:
    return ZoneInfo(_EXCHANGE_TIMEZONE_NAMES.get(timezone_id, timezone_id))


def in_trading_session(now: _Boundary, opening: _Boundary, closing: _Boundary) -> bool:
    return opening <= now < closing


def tws_trading_hours_open(trading_hours: str, now: datetime) -> bool | None:
    """Evaluate TWS tradingHours; legacy and unrecognized entries retain TWS semantics."""
    current_date = now.strftime("%Y%m%d")
    current_time = now.strftime("%H%M")
    for entry in trading_hours.split(";"):
        if not entry.startswith(current_date):
            continue
        if "CLOSED" in entry:
            return False
        parts = entry.split("-")
        if len(parts) != 2:
            return None
        start_fields, end_fields = (part.split(":") for part in parts)
        if (
            len(start_fields) < 2
            or len(end_fields) < 2
            or not start_fields[1]
            or not end_fields[1]
        ):
            return None
        return in_trading_session(current_time, start_fields[1], end_fields[1])

    if "NYSESTD" in trading_hours or trading_hours.count(":") == 1:
        parts = trading_hours.split(":")
        if len(parts) >= 2 and "-" in parts[1]:
            start, end, *_ = parts[1].split("-")
            return in_trading_session(current_time, start, end)
    return None


def format_occ_symbol(root: str, expiry: date, right: str, strike: Decimal) -> str:
    """Build the IBKR local option symbol (OCC's fixed-width layout)."""
    if not _OCC_ROOT.fullmatch(root) or len(root) > 6:
        raise ValueError("Invalid OCC root")
    if right not in {"C", "P"} or not 2000 <= expiry.year < 2100:
        raise ValueError("Invalid OCC right or expiry")
    if not strike.is_finite() or not 0 <= strike < 100_000:
        raise ValueError("Invalid OCC strike")
    scaled = strike * 1000
    if scaled != scaled.to_integral_value():
        raise ValueError("OCC strike must be representable in thousandths")
    return f"{root:<6}{expiry:%y%m%d}{right}{int(scaled):08d}"


def parse_occ_symbol(symbol: str) -> tuple[str, date, str, Decimal]:
    """Parse a canonical, padded OCC local option symbol; raise ValueError if invalid."""
    match = _OCC_SYMBOL.fullmatch(symbol)
    if not match:
        raise ValueError("Invalid OCC symbol")
    padded_root, digits, right, strike = match.groups()
    root = padded_root.rstrip()
    if not _OCC_ROOT.fullmatch(root):
        raise ValueError("Invalid OCC root")
    expiry = date(2000 + int(digits[:2]), int(digits[2:4]), int(digits[4:]))
    return root, expiry, right, Decimal(strike).scaleb(-3)
