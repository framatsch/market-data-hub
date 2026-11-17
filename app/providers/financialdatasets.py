"""Pay-per-request Financial Datasets, implemented against its pinned schema."""

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.market_hours import ET, as_utc, week_monday
from app.models.company import CompanyProfile
from app.models.earnings import EarningsEvent
from app.models.price import PriceBar, PriceQuote
from app.providers.base import (
    BaseCompanyProvider,
    BaseEarningsProvider,
    BasePriceProvider,
)
from app.providers.metered import MeteredHttpProvider
from app.utils.errors import (
    CapabilityNotSupportedError,
    DataNotFoundError,
    DataValidationError,
    ProviderError,
)


def _filing_time(row: dict[str, Any]) -> datetime:
    raw = row.get("filing_datetime")
    if raw:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=ET) if parsed.tzinfo is None else parsed.astimezone(ET)
    return datetime.combine(date.fromisoformat(row["filing_date"]), time(), ET)


def _report_time(row: dict[str, Any]) -> str:
    window = row.get("filing_window")
    if window == "PRE_MARKET":
        return "bmo"
    if window == "DURING_MARKET":
        return "during"
    if window == "AFTER_HOURS" and row.get("filing_datetime"):
        local = _filing_time(row).time()
        if local >= time(16):
            return "amc"
        if local < time(4):
            return "bmo"
    return "unknown"


class FinancialDatasetsProvider(MeteredHttpProvider, BasePriceProvider, BaseCompanyProvider, BaseEarningsProvider):
    name = "financialdatasets"
    base_url = "https://api.financialdatasets.ai"
    earnings_upcoming = False
    native_intervals = frozenset({"1d", "1w"})
    price_adjustment = "unknown"

    def _http_error(self, error: httpx.HTTPStatusError, symbol: str | None):
        if error.response.status_code in (401, 402):
            try:
                message = error.response.json().get("message", "Missing key or exhausted credit")
            except ValueError:
                message = "Missing key or exhausted credit"
            return ProviderError(str(message), "PROVIDER_NOT_AVAILABLE", {"provider": self.name, "status_code": error.response.status_code})
        return super()._http_error(error, symbol)

    async def _pages(self, path: str, params: dict[str, Any], symbol: str, field: str) -> list[dict[str, Any]]:
        result = []
        seen: set[str] = set()
        while True:
            payload = await self._request(path, params, symbol)
            result.extend(payload.get(field, []))
            next_page = payload.get("next_page_url")
            if not next_page:
                return result
            parsed = urlsplit(next_page)
            # Never forward credentials to a pagination URL on another host.
            if (parsed.scheme != "https" or parsed.netloc != "api.financialdatasets.ai"
                    or parsed.path != path or next_page in seen or parsed.fragment):
                raise ProviderError("Unsafe or repeated Financial Datasets pagination URL.")
            seen.add(next_page)
            # Follow the opaque cursor as-is; don't reconstruct its original filters.
            params = dict(httpx.QueryParams(parsed.query))

    async def get_upcoming_earnings(self, start: date, end: date, roots: list[str] | None):
        raise CapabilityNotSupportedError(self.name, "upcoming earnings", sec_type="stock", supported=[])

    async def get_earnings_history(self, root: str) -> list[EarningsEvent]:
        root = root.upper()
        rows = await self._pages("/earnings", {"ticker": root, "limit": 40}, root, "earnings")
        if not rows:
            raise DataNotFoundError("Earnings", root)
        by_period = defaultdict(list)
        for row in rows:
            by_period[row["report_period"]].append(row)
        received = datetime.now(UTC)
        result = []
        for period, filings in by_period.items():
            releases = [row for row in filings if row["source_type"] == "8-K"]
            row = min(releases or filings, key=_filing_time)
            actual = (row.get("quarterly") or {}).get("earnings_per_share")
            result.append(EarningsEvent(
                symbol=root, provider=self.name, report_date=date.fromisoformat(row["filing_date"]),
                fiscal_period_end=date.fromisoformat(period), reported=True,
                report_time=_report_time(row), eps_actual=Decimal(str(actual)) if actual is not None else None,
                currency=row.get("currency"), updated_at=received,
            ))
        return sorted(result, key=lambda event: event.report_date)

    async def get_historical_prices(self, symbol: str, interval: str, start: datetime, end: datetime, extended_hours: bool = False, sec_type: str = "stock") -> list[PriceBar]:
        if interval not in self.native_intervals:
            raise DataValidationError(f"Unsupported Financial Datasets interval: {interval}")
        symbol = symbol.upper()
        rows = await self._pages("/prices", {
            "ticker": symbol, "interval": "day" if interval == "1d" else "week",
            "start_date": start.date().isoformat(), "end_date": end.date().isoformat(),
        }, symbol, "prices")
        if not rows:
            raise DataNotFoundError("Prices", symbol)
        result = []
        for row in rows:
            instant = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
            day = as_utc(instant).astimezone(ET).date()
            timestamp = datetime.combine(day, time(), ET)
            if interval == "1w":
                timestamp = datetime.combine(week_monday(day), time(), UTC)
            if not as_utc(start) <= as_utc(timestamp) <= as_utc(end):
                continue
            result.append(PriceBar(symbol=symbol, start=timestamp,
                end=timestamp + timedelta(days=7 if interval == "1w" else 1) - timedelta(seconds=1),
                open=Decimal(str(row["open"])), high=Decimal(str(row["high"])), low=Decimal(str(row["low"])),
                close=Decimal(str(row["close"])), volume=int(row.get("volume") or 0), provider=self.name))
        return sorted(result, key=lambda bar: bar.start)

    async def get_last_price(self, symbol: str, market_data_type: int | None = None, sec_type: str = "stock") -> PriceQuote:
        symbol = symbol.upper()
        row = (await self._request("/prices/snapshot", {"ticker": symbol}, symbol)).get("snapshot")
        if not row or row.get("price") is None:
            raise DataNotFoundError("Prices", symbol)
        return PriceQuote(symbol=symbol, price=Decimal(str(row["price"])), currency="USD", provider=self.name,
                          timestamp=datetime.fromtimestamp(float(row["time_milliseconds"]) / 1000, UTC))

    async def get_company_profile(self, symbol: str) -> CompanyProfile:
        symbol = symbol.upper()
        row = (await self._request("/company/facts", {"ticker": symbol}, symbol)).get("company_facts")
        if not row:
            raise DataNotFoundError("Company", symbol)
        return CompanyProfile(symbol=symbol, name=row["name"], exchange=row.get("exchange", ""), currency="USD",
                              sector=row.get("sector"), industry=row.get("industry"), provider=self.name)

    async def search_companies(self, query: str):
        raise CapabilityNotSupportedError(self.name, "company search", sec_type="stock", supported=[])
