# market-data-hub - FastAPI data service for market and company data
# Copyright (C) 2026  Market Data Hub Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Central symbol parser: ``[<NS>:]<ROOT>`` notation and ``sec_type`` vocabulary."""

from dataclasses import dataclass
from typing import Literal, cast, get_args

from app.utils.errors import DataValidationError

SecType = Literal["stock", "etf", "index", "future", "option"]

SEC_TYPES: frozenset[str] = frozenset(get_args(SecType))

_PREFIX_TO_TYPE: dict[str, SecType] = {"F": "future", "I": "index", "O": "option"}
_TYPE_TO_PREFIX = {sec_type: prefix for prefix, sec_type in _PREFIX_TO_TYPE.items()}
_ALIAS_TO_TYPE: dict[str, SecType] = {"^": "index", "/": "future"}
_NATIVE_MARKERS = (".", "$")
_LEGACY_SEC_TYPES = {"stk": "stock"}

PRICE_TYPES: frozenset[SecType] = frozenset({"stock", "etf", "index", "future"})
VOLATILITY_TYPES: frozenset[SecType] = PRICE_TYPES
OPTION_UNDERLYING_TYPES: frozenset[SecType] = frozenset({"stock", "etf", "index"})
COMPANY_TYPES: frozenset[SecType] = frozenset({"stock", "etf"})
STREAM_TYPES: frozenset[SecType] = PRICE_TYPES


@dataclass(frozen=True, slots=True)
class ParsedSymbol:
    root: str
    sec_type: SecType

    @property
    def canonical(self) -> str:
        prefix = _TYPE_TO_PREFIX.get(self.sec_type)
        return f"{prefix}:{self.root}" if prefix else self.root

    def __str__(self) -> str:
        return self.canonical


def normalize_sec_type(sec_type: str | None) -> SecType | None:
    """Lower-case `sec_type`, map legacy `STK`, and reject unknown values."""
    if sec_type is None:
        return None
    value = sec_type.strip().lower()
    if not value:
        return None
    value = _LEGACY_SEC_TYPES.get(value, value)
    if value not in SEC_TYPES:
        raise DataValidationError(
            f"Invalid sec_type: {sec_type!r}",
            {"sec_type": sec_type, "supported": sorted(SEC_TYPES)},
        )
    return cast(SecType, value)


def canonical_symbol(root: str, sec_type: str) -> str:
    """Canonical form of a provider-level (root, sec_type) pair, e.g. ``F:ES``."""
    resolved = normalize_sec_type(sec_type) or "stock"
    return ParsedSymbol(root=root.upper(), sec_type=resolved).canonical


def _split_prefix(text: str, raw: str) -> tuple[SecType | None, str]:
    if text[0] in _NATIVE_MARKERS:
        root = text[1:].upper()
        suggestion = f"I:{root}" if root else "I:<ROOT>"
        raise DataValidationError(
            f"Provider-native symbol notation is not accepted: {raw!r}",
            {"symbol": raw, "suggestion": suggestion},
        )
    if text[0] in _ALIAS_TO_TYPE:
        return _ALIAS_TO_TYPE[text[0]], text[1:].strip()
    if ":" in text:
        prefix, _, root = text.partition(":")
        prefix_type = _PREFIX_TO_TYPE.get(prefix.strip().upper())
        if prefix_type is None:
            raise DataValidationError(
                f"Unknown symbol prefix: {prefix.strip()!r}",
                {"symbol": raw, "supported_prefixes": sorted(_PREFIX_TO_TYPE)},
            )
        return prefix_type, root.strip()
    return None, text


def parse_symbol(
    raw: str,
    sec_type: str | None = None,
    *,
    allowed: frozenset[SecType] | None = None,
) -> ParsedSymbol:
    """Resolve a raw symbol and optional `sec_type` into a `ParsedSymbol`.

    Every failure raises `DataValidationError` (HTTP 422).
    """
    text = (raw or "").strip()
    if not text:
        raise DataValidationError("Symbol must not be empty", {"symbol": raw})
    explicit = normalize_sec_type(sec_type)
    prefix_type, root = _split_prefix(text, raw)
    root = root.upper()
    if not root:
        raise DataValidationError(f"Symbol has an empty root: {raw!r}", {"symbol": raw})
    if ":" in root:
        raise DataValidationError(
            f"Symbol root must not contain ':': {raw!r}", {"symbol": raw}
        )
    if root[0] in _NATIVE_MARKERS:
        raise DataValidationError(
            f"Provider-native symbol notation is not accepted: {raw!r}",
            {"symbol": raw, "suggestion": f"I:{root[1:]}"},
        )

    resolved: SecType
    if prefix_type is not None:
        if explicit is not None and explicit != prefix_type:
            raise DataValidationError(
                f"Symbol {raw!r} denotes '{prefix_type}' but sec_type is '{explicit}'",
                {"symbol": raw, "prefix_type": prefix_type, "sec_type": explicit},
            )
        resolved = prefix_type
    else:
        resolved = explicit or "stock"

    if allowed is not None and resolved not in allowed:
        raise DataValidationError(
            f"Instrument type '{resolved}' is not supported here",
            {"symbol": raw, "sec_type": resolved, "supported": sorted(allowed)},
        )
    return ParsedSymbol(root=root, sec_type=resolved)


def strip_option_prefix(option_id: str) -> str:
    """Remove an optional ``O:`` prefix from an option contract id and upper-case it."""
    text = option_id.strip()
    if text[:2].upper() == "O:":
        text = text[2:].strip()
    if not text:
        raise DataValidationError(
            "Option id must not be empty", {"option_id": option_id}
        )
    return text.upper()
