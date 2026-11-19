"""Free-tier Alpha Vantage: announced calendar, quarterly earnings and EOD prices."""

import asyncio
import csv
import io
import re
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import httpx

from app.market_hours import ET, as_utc, week_monday
from app.models.earnings import EarningsEvent, earnings_today
from app.models.price import PriceBar, PriceQuote
from app.providers.base import (
    BaseEarningsHistoryProvider,
    BaseEarningsUpcomingProvider,
    BasePriceProvider,
)
from app.providers.credentials import get_provider_credential_sync
from app.providers.metered import MeteredHttpProvider
from app.utils.errors import (
    DataNotFoundError,
    DataValidationError,
    ProviderError,
    ProviderNotEntitledError,
    ProviderQuotaExhaustedError,
    ProviderTimeoutError,
)


def _decimal(value: Any) -> Decimal | None:
    if value is None or str(value).strip() in {"", "None", "null"}:
        return None
    result = Decimal(str(value))
    return result if result.is_finite() else None


def calendar_horizon(end: date, today: date | None = None) -> str:
    today = today or earnings_today()
    for months in (3, 6):
        # Actual calendar months, not an approximation of 90/180 days.
        month_index = today.year * 12 + today.month - 1 + months
        year, month = divmod(month_index, 12)
        import calendar

        boundary = date(year, month + 1, min(today.day, calendar.monthrange(year, month + 1)[1]))
        if end <= boundary:
            return f"{months}month"
    return "12month"


class AlphaVantageProvider(MeteredHttpProvider, BasePriceProvider, BaseEarningsUpcomingProvider, BaseEarningsHistoryProvider):
    name = "alphavantage"
    base_url = "https://www.alphavantage.co"
    minimum_spacing = 1.05
    native_intervals = frozenset({"1d", "1w"})
    price_adjustment = "none"
    upcoming_mode = "calendar"

    async def _auth(self, params):
        key = await asyncio.to_thread(get_provider_credential_sync, self.name, "api_key")
        return {**params, "apikey": key}, {}

    async def _decode(self, response: httpx.Response, symbol: str | None) -> Any:
        if not response.text.lstrip().startswith("{"):
            return response.text
        payload = response.json()
        for field in ("Information", "Note", "Error Message"):
            if field not in payload:
                continue
            message = str(payload[field])
            text = message.lower()
            # The real burst notice also advertises 25/day and premium plans.
            if any(token in text for token in ("per second", "per-second", "burst", "per minute", "per-minute", "spreading out")):
                raise ProviderTimeoutError(self.name, {"period": "burst"})
            if ("api key" in text or "apikey" in text) and any(token in text for token in ("invalid", "missing", "incorrect")):
                raise ProviderError("Invalid Alpha Vantage API key.", "PROVIDER_NOT_AVAILABLE", {"provider": self.name})
            if re.search(r"(?:requests?\s+per\s+day|daily.*(?:limit|quota|exhaust))", text):
                await self.budget.exhaust_day()
                raise ProviderQuotaExhaustedError(self.name, "day", self.budget.day_budget)
            if "premium endpoint" in text or "premium feature" in text:
                raise ProviderNotEntitledError(self.name, symbol=symbol, provider_message="Requested Alpha Vantage endpoint or parameter requires premium access.")
            if field == "Error Message" and symbol:
                raise DataNotFoundError("Ticker", symbol)
            raise ProviderError("Alpha Vantage returned a provider notice.", details={"provider": self.name, "notice_field": field})
        return payload

    async def get_upcoming_earnings(self, start: date, end: date, roots: list[str] | None) -> list[EarningsEvent]:
        raw = await self._request("/query", {"function": "EARNINGS_CALENDAR", "horizon": calendar_horizon(end)})
        if not isinstance(raw, str):
            raise ProviderError("Alpha Vantage calendar is not CSV")
        reader = csv.DictReader(io.StringIO(raw))
        if not {"symbol", "reportDate", "fiscalDateEnding"} <= set(reader.fieldnames or []):
            raise ProviderError("Alpha Vantage calendar is missing required columns")
        selected = {root.upper() for root in roots} if roots is not None else None
        result = []
        received = datetime.now(UTC)
        for row in reader:
            symbol = row["symbol"].upper()
            if re.search(r"-P[A-Z]+$", symbol) or (selected is not None and symbol not in selected):
                continue
            reported = date.fromisoformat(row["reportDate"])
            if not start <= reported <= end:
                continue
            result.append(EarningsEvent(
                symbol=symbol, report_date=reported,
                report_time={"pre-market": "bmo", "post-market": "amc"}.get(row.get("timeOfTheDay", ""), "unknown"),
                fiscal_period_end=date.fromisoformat(row["fiscalDateEnding"]) if row.get("fiscalDateEnding") else None,
                eps_estimate=_decimal(row.get("estimate")), currency=row.get("currency") or None,
                provider=self.name, updated_at=received,
            ))
        return sorted(result, key=lambda event: (event.report_date, event.symbol))

    async def get_earnings_history(self, root: str) -> list[EarningsEvent]:
        root = root.upper()
        payload = await self._request("/query", {"function": "EARNINGS", "symbol": root.replace(".", "-")}, root)
        if not payload or not payload.get("quarterlyEarnings"):
            raise DataNotFoundError("Earnings", root)
        received = datetime.now(UTC)
        return [EarningsEvent(
            symbol=root, report_date=date.fromisoformat(row["reportedDate"]), reported=True,
            report_time={"pre-market": "bmo", "post-market": "amc"}.get(row.get("reportTime", ""), "unknown"),
            fiscal_period_end=date.fromisoformat(row["fiscalDateEnding"]),
            eps_actual=_decimal(row.get("reportedEPS")), eps_estimate=_decimal(row.get("estimatedEPS")),
            eps_surprise=_decimal(row.get("surprise")), eps_surprise_pct=_decimal(row.get("surprisePercentage")),
            provider=self.name, updated_at=received,
        ) for row in payload["quarterlyEarnings"]]

    async def get_historical_prices(self, symbol: str, interval: str, start: datetime, end: datetime, extended_hours: bool = False, sec_type: str = "stock") -> list[PriceBar]:
        if interval not in self.native_intervals:
            raise DataValidationError(f"Unsupported Alpha Vantage interval: {interval}")
        symbol = symbol.upper()
        function, series = ("TIME_SERIES_DAILY", "Time Series (Daily)") if interval == "1d" else ("TIME_SERIES_WEEKLY", "Weekly Time Series")
        payload = await self._request("/query", {"function": function, "symbol": symbol.replace(".", "-")}, symbol)
        if not payload.get(series):
            raise DataNotFoundError("Prices", symbol)
        result = []
        for raw_day, row in payload[series].items():
            day = date.fromisoformat(raw_day)
            timestamp = datetime.combine(day, time(), ET)
            if interval == "1w":
                timestamp = datetime.combine(week_monday(day), time(), UTC)
            if not as_utc(start) <= as_utc(timestamp) <= as_utc(end):
                continue
            bar_end = timestamp + timedelta(days=1) - timedelta(seconds=1)
            if interval == "1w":
                bar_end = timestamp + timedelta(days=7) - timedelta(seconds=1)
            result.append(PriceBar(symbol=symbol, start=timestamp, end=bar_end,
                open=Decimal(row["1. open"]), high=Decimal(row["2. high"]), low=Decimal(row["3. low"]),
                close=Decimal(row["4. close"]), volume=int(row["5. volume"]), provider=self.name))
        return sorted(result, key=lambda bar: bar.start)

    async def get_last_price(self, symbol: str, market_data_type: int | None = None, sec_type: str = "stock") -> PriceQuote:
        symbol = symbol.upper()
        payload = await self._request("/query", {"function": "GLOBAL_QUOTE", "symbol": symbol.replace(".", "-")}, symbol)
        quote = payload.get("Global Quote", {})
        if not quote.get("05. price"):
            raise DataNotFoundError("Prices", symbol)
        day = date.fromisoformat(quote["07. latest trading day"])
        return PriceQuote(symbol=symbol, price=Decimal(quote["05. price"]), currency="USD",
            timestamp=datetime.combine(day, time(16), ET), provider=self.name,
            open=_decimal(quote.get("02. open")), high=_decimal(quote.get("03. high")), low=_decimal(quote.get("04. low")),
            volume=int(quote["06. volume"]) if quote.get("06. volume") else None)
