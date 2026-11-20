"""Pay-per-request Financial Datasets, implemented against its pinned schema."""

import logging
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha1
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.market_hours import ET, as_utc, week_monday
from app.models.company import CompanyProfile
from app.models.earnings import EarningsEvent
from app.models.news import NewsArticle
from app.models.price import PriceBar, PriceQuote
from app.providers.base import (
    BaseCompanyProvider,
    BaseEarningsHistoryProvider,
    BaseNewsProvider,
    BasePriceProvider,
)
from app.providers.metered import MeteredHttpProvider
from app.providers.news_categories import detect_category
from app.utils.errors import (
    CapabilityNotSupportedError,
    DataNotFoundError,
    DataValidationError,
    ProviderError,
)

logger = logging.getLogger(__name__)
NEWS_LIMIT = 10

# Even late SEC filers report within 90 days of period end; anything later is a comparative.
MAX_FILING_LAG = timedelta(days=120)
# Annual-minus-quarters EPS arrives unrounded (e.g. 0.9712633647579039).
EPS_PRECISION = Decimal("0.01")


def _filing_time(row: dict[str, Any]) -> datetime:
    raw = row.get("filing_datetime")
    if raw:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=ET) if parsed.tzinfo is None else parsed.astimezone(ET)
    return datetime.combine(date.fromisoformat(row["filing_date"]), time(), ET)


def _price_day(raw: str) -> date:
    # The live API sends bare trading dates although the schema documents UTC timestamps.
    if "T" not in raw:
        return date.fromisoformat(raw)
    return as_utc(datetime.fromisoformat(raw.replace("Z", "+00:00"))).astimezone(ET).date()


def _news_day(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        # The schema says date-only, but the live API also returns ISO timestamps.
        return as_utc(datetime.fromisoformat(raw)).date()


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


class FinancialDatasetsProvider(
    MeteredHttpProvider, BasePriceProvider, BaseCompanyProvider, BaseEarningsHistoryProvider, BaseNewsProvider
):
    name = "financialdatasets"
    base_url = "https://api.financialdatasets.ai"
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

    async def get_company_news(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
        limit: int = 20,
        offset: int = 0,
        language: str = "en",
        category: str | None = None,
    ) -> list[NewsArticle]:
        if language != "en":
            return []

        symbol = symbol.upper()
        rows = await self._pages("/news", {"ticker": symbol, "limit": NEWS_LIMIT}, symbol, field="news")
        articles = []
        for row in rows[:NEWS_LIMIT]:
            if not isinstance(row, dict):
                logger.debug("Skipping malformed Financial Datasets news for %s", symbol)
                continue
            title, url = row.get("title"), row.get("url")
            if not isinstance(title, str) or not title.strip() or not isinstance(url, str) or not url.strip():
                logger.debug("Skipping Financial Datasets news without a title or URL for %s", symbol)
                continue
            try:
                day = _news_day(row["date"])
            except (KeyError, TypeError, ValueError):
                logger.debug("Skipping Financial Datasets news with an invalid date for %s", symbol)
                continue
            if not from_date <= day <= to_date:
                continue
            detected = detect_category(title)
            if category and detected != category:
                continue

            source = row.get("source")
            url_hash = sha1(url.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
            articles.append(NewsArticle(
                article_id=f"{self.name}:{url_hash}", title=title, summary="",
                published_at=datetime.combine(day, time(), UTC),
                source=source if isinstance(source, str) else "", url=url, category=detected,
            ))

        articles.sort(key=lambda article: article.published_at, reverse=True)
        return articles[offset:offset + limit]

    async def get_earnings_history(self, root: str) -> list[EarningsEvent]:
        root = root.upper()
        rows = await self._pages("/earnings", {"ticker": root, "limit": 40}, root, "earnings")
        by_period = defaultdict(list)
        for row in rows:
            # Later filings repeat prior-year periods as comparatives; they are not the release.
            if _filing_time(row).date() - date.fromisoformat(row["report_period"]) <= MAX_FILING_LAG:
                by_period[row["report_period"]].append(row)
        if not by_period:
            raise DataNotFoundError("Earnings", root)
        received = datetime.now(UTC)
        result = []
        for period, filings in by_period.items():
            releases = [row for row in filings if row["source_type"] == "8-K"]
            row = min(releases or filings, key=_filing_time)
            actual = (row.get("quarterly") or {}).get("earnings_per_share")
            result.append(EarningsEvent(
                symbol=root, provider=self.name, report_date=date.fromisoformat(row["filing_date"]),
                fiscal_period_end=date.fromisoformat(period), reported=True,
                report_time=_report_time(row),
                eps_actual=Decimal(str(actual)).quantize(EPS_PRECISION, ROUND_HALF_UP) if actual is not None else None,
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
            day = _price_day(row["time"])
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
