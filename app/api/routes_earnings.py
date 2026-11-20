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

from datetime import date, timedelta
from typing import Any, Literal
from urllib.parse import quote as url_quote

from fastapi import APIRouter, Query, Request, Response

from app import response_meta
from app.cache import cache
from app.config import settings
from app.dependencies import EarningsServiceDep
from app.models.common import EnvelopeMeta, ResponseEnvelope
from app.models.earnings import EarningsEvent, NextEarnings, earnings_today
from app.observability.headers import CSV_RESPONSE_HEADERS, DATA_RESPONSE_HEADERS
from app.services.earnings_service import (
    EarningsResult,
    NextResult,
    parse_symbol_list,
)
from app.utils.csv_export import to_csv

router = APIRouter(prefix="/earnings", tags=["Earnings"])

SymbolsQuery = Query(
    ...,
    description=(
        "Comma-separated stock symbols, 1-50 after de-duplication, e.g. `AAPL,MSFT`. "
        "ETFs are answered as `not_applicable`; index, future and option symbols "
        "(`I:SPX`, `F:ES`, `O:...`) are rejected with 422."
    ),
    examples=["AAPL,MSFT,SPY"],
)
ProviderQuery = Query(
    None,
    description=(
        "Earnings provider (`alphavantage`, `earningsapi`, `financialdatasets`). Without it "
        "the upcoming default serves upcoming events and the history default reported ones."
    ),
)
EventKind = Literal["all", "upcoming", "reported"]
KindQuery = Query(
    "all",
    description=(
        "`all` (default), `upcoming` (announced, `reported: false`) or `reported` "
        "(`reported: true`). `upcoming` requests no history, `reported` no calendar."
    ),
)


def earnings_envelope(data: Any, result: EarningsResult | NextResult) -> Any:
    """Envelope with provenance: provider, data age, stale flag, per-symbol status."""
    meta = response_meta.current().to_meta()
    meta.setdefault("stale", False)
    if result.provider is not None:
        meta["provider"] = result.provider
    providers = getattr(result, "providers", None)
    if providers:
        meta["providers"] = providers
    if isinstance(result, EarningsResult):
        meta["symbols"] = [
            item.model_dump(mode="json", exclude_none=True) for item in result.symbols
        ]
    return ResponseEnvelope(data=data, meta=EnvelopeMeta(**meta))


def csv_response(events: list[EarningsEvent], name: str) -> Response:
    filename = f"{url_quote(name, safe='')}.csv"
    content_type, body = to_csv(events, filename=filename)
    return Response(
        body,
        media_type=content_type,
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            **response_meta.csv_headers(),
        },
    )


def order_by_request(result: Any, requested: list[str]) -> Any:
    """Order the rows of a `next` envelope (model or cached dict) by `requested`."""
    cached = isinstance(result, dict)
    rows = result.get("data") if cached else result.data
    if not isinstance(rows, list):
        return result

    def name(row: Any) -> str:
        return row["symbol"] if cached else row.symbol

    by_symbol = {name(row): row for row in rows}
    ordered = [by_symbol[symbol] for symbol in requested if symbol in by_symbol]
    if cached:
        return {**result, "data": ordered}
    result.data = ordered
    return result


def restore_next_order(result: Any, request: Request | None) -> Any:
    """`next` is cached in canonical order; answer in the request's order."""
    if request is None or not isinstance(result, dict | ResponseEnvelope):
        return result
    try:
        requested = [
            symbol.canonical
            for symbol in parse_symbol_list(request.query_params.get("symbols", ""))
        ]
    except Exception:
        return result
    return order_by_request(result, requested)


@router.get(
    "/calendar", response_model=ResponseEnvelope[list[EarningsEvent]],
    responses={200: {"headers": CSV_RESPONSE_HEADERS}},
)
@cache(expire=settings.CACHE_TTL_EARNINGS_SECONDS, key="earnings:calendar")
async def get_earnings_calendar(
    service: EarningsServiceDep,
    symbols: str = SymbolsQuery,
    from_date: date | None = Query(
        None, alias="from", description="First report date (default: today - 30 days)."
    ),
    to_date: date | None = Query(
        None, alias="to", description="Last report date (default: today + 90 days)."
    ),
    kind: EventKind = KindQuery,
    provider: str | None = ProviderQuery,
    format: Literal["json", "csv"] = Query("json", description="`json` or `csv`."),
) -> Any:
    """Earnings events of up to 50 stocks in a date range, oldest first.

    Upcoming events come from the upcoming provider, past events from the history
    provider (`kind` selects `upcoming`, `reported` or `all`). Providers with a
    market-wide calendar request it once for all symbols; per-symbol providers
    (`earningsapi`) use a day-calendar window plus per-symbol requests within their
    request budget. Revenue fields are filled where the provider delivers them. The calendar lists
    **announced dates only**: a company that has not announced yet has no event,
    and MDH never estimates a date. `meta.symbols` holds per symbol `status`
    (`ok`, `not_applicable`, `not_found`, `error`) and `history` (`complete`,
    `pending` when the provider budget was used up, `not_requested`).
    `meta.stale` is true when stored events were served because the provider
    failed or its request budget is exhausted.

    - `GET /earnings/calendar?symbols=AAPL,MSFT&from=2026-11-17&to=2027-02-28`
    - CSV: `...&format=csv` (header `X-MDH-Data-As-Of`)
    """
    today = earnings_today()
    result = await service.calendar(
        parse_symbol_list(symbols),
        from_date or today - timedelta(days=30),
        to_date or today + timedelta(days=90),
        provider.lower() if provider else None,
        kind,
    )
    if format == "csv":
        return csv_response(result.events, "earnings_calendar")
    return earnings_envelope(result.events, result)


@router.get(
    "/next", response_model=ResponseEnvelope[list[NextEarnings]],
    responses={200: {"headers": DATA_RESPONSE_HEADERS}},
)
@cache(
    expire=settings.CACHE_TTL_EARNINGS_SECONDS,
    key="earnings:next",
    post=restore_next_order,
)
async def get_next_earnings(
    service: EarningsServiceDep,
    symbols: str = SymbolsQuery,
    provider: str | None = ProviderQuery,
) -> Any:
    """The next announced earnings event per symbol, in request order.

    One row per requested symbol: `event` (earliest event on or after today in New
    York, or `null`), `days_until`, `last_reported` (latest stored reported event,
    never fetched by this endpoint) and `status` (`ok`, `none_scheduled`,
    `not_applicable` for ETFs). Answered from the provider's market-wide calendar
    only: at most one provider request for all symbols and none for history.
    `date_status` of an event is what the provider states (`unknown` for Alpha
    Vantage). Providers without upcoming dates answer 501.

    - `GET /earnings/next?symbols=AAPL,MSFT,SPY`
    """
    result = await service.next(
        parse_symbol_list(symbols), provider.lower() if provider else None
    )
    result.rows.sort(key=lambda row: row.symbol)
    return earnings_envelope(result.rows, result)
