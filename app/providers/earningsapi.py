"""Free-tier EarningsAPI: per-symbol earnings events and a market-wide day calendar."""

import asyncio
import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.models.earnings import EarningsEvent, ReportTime
from app.providers.base import BaseEarningsHistoryProvider, BaseEarningsUpcomingProvider
from app.providers.credentials import get_provider_credential_sync
from app.providers.metered import MeteredHttpProvider
from app.utils.errors import (
    AppError,
    DataNotFoundError,
    ProviderError,
    ProviderQuotaExhaustedError,
    ProviderTimeoutError,
    map_httpx_http_error,
)

_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,14}$")
_GROUP_TIMES: dict[str, ReportTime] = {"pre": "bmo", "after": "amc", "notSupplied": "unknown"}
_TIMES: dict[Any, ReportTime] = {"time-pre-market": "bmo", "time-after-hours": "amc"}


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _surprise(estimate: Decimal | None, actual: Decimal | None) -> tuple[Decimal | None, Decimal | None]:
    if estimate is None or actual is None:
        return None, None
    surprise = actual - estimate
    pct = (surprise / abs(estimate) * 100).quantize(Decimal("0.0001")) if estimate != 0 else None
    return surprise, pct


def _header_int(response: httpx.Response, name: str) -> int | None:
    try:
        return int(response.headers[name])
    except (KeyError, ValueError):
        return None


class EarningsApiProvider(MeteredHttpProvider, BaseEarningsUpcomingProvider, BaseEarningsHistoryProvider):
    name = "earningsapi"
    base_url = "https://api.earningsapi.com"
    minimum_spacing = 1.0  # free tier: 60 requests per minute
    upcoming_mode = "symbol"
    earnings_day_calendar = True

    async def _auth(self, params):
        key = await asyncio.to_thread(get_provider_credential_sync, self.name, "api_key")
        return {**params, "apikey": key}, {}

    def _http_error(self, error: httpx.HTTPStatusError, symbol: str | None) -> AppError:
        response = error.response
        status = response.status_code
        if status in (401, 403):
            return ProviderError(
                "Invalid EarningsAPI key.", "PROVIDER_NOT_AVAILABLE",
                {"provider": self.name, "status_code": status},
            )
        if status == 404 and symbol:
            return DataNotFoundError("Earnings", symbol)
        if status == 429:
            if _header_int(response, "X-Daily-Remaining") == 0:
                return ProviderQuotaExhaustedError(self.name, "day", self.budget.day_budget)
            if _header_int(response, "X-Quota-Remaining") == 0:
                return ProviderQuotaExhaustedError(self.name, "month", self.budget.month_budget)
            timeout = ProviderTimeoutError(self.name, {"period": "burst"})
            try:
                timeout.retry_after = float(response.headers["Retry-After"])  # type: ignore[attr-defined]
            except (KeyError, ValueError):
                pass
            return timeout
        return map_httpx_http_error(
            provider=self.name, error=error, entity="Ticker", identifier=symbol or self.name
        )

    async def _request(self, path: str, params: dict[str, Any], symbol: str | None = None) -> Any:
        try:
            return await super()._request(path, params, symbol)
        except ProviderQuotaExhaustedError as exc:
            if exc.details.get("period") == "day":
                await self.budget.exhaust_day()
            raise

    # ----------------------------------------------------------------- mapping

    def _event(
        self,
        row: dict[str, Any],
        symbol: str,
        report_date: date,
        report_time: ReportTime,
        received: datetime,
    ) -> EarningsEvent:
        estimate, actual = _decimal(row.get("epsEstimate")), _decimal(row.get("eps"))
        surprise, surprise_pct = _surprise(estimate, actual)
        return EarningsEvent(
            symbol=symbol, report_date=report_date, report_time=report_time,
            eps_estimate=estimate, eps_actual=actual,
            eps_surprise=surprise, eps_surprise_pct=surprise_pct,
            revenue_estimate=_decimal(row.get("revenueEstimate")),
            revenue_actual=_decimal(row.get("revenue")),
            currency="USD", provider=self.name, updated_at=received,
        )

    async def get_symbol_earnings(self, root: str) -> list[EarningsEvent]:
        root = root.upper()
        payload = await self._request("/v2/earnings", {"symbol": root}, root)
        if not isinstance(payload, list):
            raise ProviderError("Unexpected EarningsAPI earnings response.")
        if not payload:
            raise DataNotFoundError("Earnings", root)
        received = datetime.now(UTC)
        events: dict[date, EarningsEvent] = {}
        for row in payload:
            if not isinstance(row, dict) or not isinstance(row.get("date"), str):
                raise ProviderError("Unexpected EarningsAPI earnings entry.")
            day = date.fromisoformat(row["date"])
            events.setdefault(day, self._event(row, root, day, _TIMES.get(row.get("time"), "unknown"), received))
        return sorted(events.values(), key=lambda e: e.report_date, reverse=True)

    async def get_earnings_history(self, root: str) -> list[EarningsEvent]:
        events = [e for e in await self.get_symbol_earnings(root) if e.reported]
        if not events:
            raise DataNotFoundError("Earnings", root.upper())
        return events

    async def get_earnings_for_date(self, day: date) -> list[EarningsEvent]:
        payload = await self._request("/v2/calendar/earnings", {"date": day.isoformat()})
        if not isinstance(payload, dict) or not all(isinstance(payload.get(g), list) for g in _GROUP_TIMES):
            raise ProviderError("Unexpected EarningsAPI calendar response.")
        received = datetime.now(UTC)
        events: dict[str, EarningsEvent] = {}
        for group, report_time in _GROUP_TIMES.items():
            for row in payload[group]:
                symbol = str(row.get("symbol") or "").strip().upper() if isinstance(row, dict) else ""
                if not _SYMBOL.match(symbol):
                    continue
                known = events.get(symbol)
                if known is not None and (known.report_time != "unknown" or report_time == "unknown"):
                    continue
                events[symbol] = self._event(row, symbol, day, report_time, received)
        return sorted(events.values(), key=lambda e: e.symbol)

    async def test_connection(self) -> dict[str, Any]:
        try:
            await self._request("/v2/earnings", {"symbol": "AAPL"}, "AAPL")
            return {"status_code": 200, "success": True, "message": f"Connected to {self.name}", "details": {"ticker": "AAPL"}}
        except AppError as exc:
            status = 429 if exc.code == "PROVIDER_QUOTA_EXHAUSTED" else 503
            return {"status_code": status, "success": False, "message": exc.message, "details": exc.details}
