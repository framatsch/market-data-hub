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

from datetime import UTC, datetime
from typing import Any

import structlog

from app import response_meta
from app.admin.runtime import get_provider_config_repository
from app.models.common import MarketStatus
from app.models.price import PriceBar, PriceQuote
from app.observability.metrics import record_history_store_read
from app.providers.base import BasePriceProvider
from app.providers.registry import ProviderRegistry, get_registry
from app.store import engine, repository
from app.store.repository import SeriesKey
from app.store.sync import Loaded, Profile, history_sync, is_transient
from app.utils.errors import AppError, CapabilityNotSupportedError, DataValidationError
from app.utils.intervals import (
    aggregate_bars,
    derived_intervals,
    normalize_interval,
    select_source_interval,
    widen_range,
)
from app.utils.symbols import ParsedSymbol


def _as_utc(value: datetime) -> datetime:
    """Interpret legacy naive request dates as UTC; preserve aware instants."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _check_support(
    provider: BasePriceProvider, operation: str, symbol: ParsedSymbol
) -> None:
    """501 before any provider call when the hub has no mapping for this type."""
    supported = (
        provider.price_sec_types
        if operation == "last"
        else provider.price_history_sec_types
    )
    if symbol.sec_type not in supported:
        raise CapabilityNotSupportedError(
            provider.name,
            operation,
            sec_type=symbol.sec_type,
            supported=sorted(supported),
        )


async def _stored_intervals(provider: str) -> list[str]:
    """Intervals the history store keeps for `provider` (default: daily only)."""
    try:
        config = await get_provider_config_repository().get(provider)
    except Exception:
        return ["1d"]
    return config.history_store_intervals


class PriceService:
    def __init__(self, registry: ProviderRegistry | None = None) -> None:
        self.registry = registry or get_registry()

    async def get_latest_price(
        self,
        symbol: ParsedSymbol,
        provider_name: str | None = None,
        market_data_type: int | None = None,
    ) -> PriceQuote:
        async with self.registry.use_price_provider(provider_name) as provider:
            structlog.contextvars.bind_contextvars(provider=provider.name)
            _check_support(provider, "last", symbol)
            quote = await provider.get_last_price(
                symbol.root, market_data_type, symbol.sec_type
            )
            return quote.model_copy(update={"symbol": symbol.canonical})

    async def get_historical_prices(
        self,
        symbol: ParsedSymbol,
        interval: str,
        start: datetime,
        end: datetime,
        extended_hours: bool = False,
        provider_name: str | None = None,
    ) -> list[PriceBar]:
        start, end = _as_utc(start), _as_utc(end)
        interval = normalize_interval(interval)
        effective = provider_name or self.registry.default_price_provider
        if (
            effective
            and engine.store_enabled()
            and interval in await _stored_intervals(effective)
        ):
            stored = await self._history_from_store(
                symbol, interval, start, end, extended_hours, effective
            )
            if stored is not None:
                return stored
            record_history_store_read("prices", "bypass")
        return (
            await self._load_bars(
                symbol, interval, start, end, extended_hours, provider_name
            )
        ).items

    def _native(self, provider_name: str, interval: str) -> frozenset[str]:
        instance = self.registry.get_provider_instance(provider_name)
        native = getattr(instance, "native_intervals", None)
        return native if isinstance(native, frozenset) else frozenset({interval})

    async def _load_bars(
        self,
        symbol: ParsedSymbol,
        interval: str,
        start: datetime,
        end: datetime,
        extended_hours: bool,
        provider_name: str | None,
    ) -> Loaded[PriceBar]:
        """Bars of `interval`: natively from the provider or derived from smaller bars."""
        async with self.registry.use_price_provider(provider_name) as provider:
            structlog.contextvars.bind_contextvars(provider=provider.name)
            _check_support(provider, "history", symbol)
            native = provider.native_intervals
            if not isinstance(native, frozenset):  # stand-ins without a declaration
                native = frozenset({interval})
            source = (
                None if interval in native else select_source_interval(interval, native)
            )
            if interval not in native and source is None:
                raise DataValidationError(
                    f"Interval '{interval}' is not supported by provider '{provider.name}'",
                    details={
                        "provider": provider.name,
                        "interval": interval,
                        "native_intervals": sorted(native),
                        "derived_intervals": derived_intervals(native),
                    },
                )
            call_start, call_end = start, end
            if source is not None:
                call_start, call_end = widen_range(interval, start, end)
            bars = await provider.get_historical_prices(
                symbol.root,
                source or interval,
                call_start,
                call_end,
                extended_hours,
                sec_type=symbol.sec_type,
            )
        response_meta.current().record_fetch()
        items = [bar.model_copy(update={"symbol": symbol.canonical}) for bar in bars]
        if source is not None:
            items = [
                bar
                for bar in aggregate_bars(
                    [b for b in items if call_start <= b.start <= call_end],
                    interval,
                    source,
                )
            ]
        found = next((b.source_instrument for b in items if b.source_instrument), None)
        return Loaded(items=items, source_instrument=found, sec_type=symbol.sec_type)

    async def _history_from_store(
        self,
        symbol: ParsedSymbol,
        interval: str,
        start: datetime,
        end: datetime,
        extended_hours: bool,
        provider_name: str,
    ) -> list[PriceBar] | None:
        intraday = interval in {"1h", "4h"}
        flag = extended_hours and intraday
        key = SeriesKey("prices", symbol.canonical, provider_name, interval, flag)
        profile = Profile("prices", interval, flag)
        meta = response_meta.current()
        native = self._native(provider_name, interval)
        source_interval = (
            None if interval in native else select_source_interval(interval, native)
        )

        async def loader(load_start: datetime, load_end: datetime) -> Loaded[PriceBar]:
            return await self._load_bars(
                symbol, interval, load_start, load_end, extended_hours, provider_name
            )

        try:
            served = await history_sync.serve(
                key,
                profile,
                start,
                end,
                loader,
                force=meta.no_cache,
                sec_type=symbol.sec_type,
                source_interval=source_interval,
            )
        except AppError as exc:
            if interval == "1d" and is_transient(exc):
                fallback = await self._fallback_bars(
                    symbol, start, end, provider_name, exc.code
                )
                if fallback is not None:
                    return fallback
            raise
        if served is None:
            return None
        if served.data_as_of is not None:
            meta.data_as_of = served.data_as_of
        if served.stale:
            meta.mark_stale(served.stale_reason or "PROVIDER_ERROR")
        return served.items

    async def _fallback_bars(
        self,
        symbol: ParsedSymbol,
        start: datetime,
        end: datetime,
        provider_name: str,
        reason: str,
    ) -> list[PriceBar] | None:
        """Daily bars of another provider when the requested one failed (D7)."""
        profile = Profile("prices", "1d")
        rs, re = profile.request_range(start, end)
        need = min(re, profile.newest_closed(datetime.now(UTC)))

        async def lookup() -> list[Any]:
            async with engine.session_scope() as session:
                candidates = await repository.covering_price_series(
                    session, symbol.canonical, provider_name, rs
                )
                for series in candidates:
                    if series.covered_to is None or series.covered_to < need:
                        continue
                    bars = await repository.read_bars(session, series, rs, re)
                    return [series, bars]
            return []

        found: list[Any] = await engine.guarded(lookup, [])
        if not found:
            return None
        series, bars = found
        meta = response_meta.current()
        if series.synced_at is not None:
            meta.data_as_of = series.synced_at
        meta.mark_stale(reason, series.key.provider)
        record_history_store_read("prices", "fallback_provider")
        return bars

    async def get_market_status(self, provider_name: str | None = None) -> MarketStatus:
        async with self.registry.use_price_provider(provider_name) as provider:
            structlog.contextvars.bind_contextvars(provider=provider.name)
            return await provider.get_market_status()


price_service = PriceService()
