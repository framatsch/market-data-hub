## Why

VisioTrade already carries `earningsDate`, `daysToEarnings` and `earningsSource` in its watchlist overview, but every row is `null` and the source is always `"unavailable"` because MDH has no earnings data. Its credit-spread filters state explicitly that earnings are not checked, although an earnings release inside the DTE is the most common reason to skip a short-premium trade. Trade analytics (positions held through earnings, earnings-window-free correlations, actual versus implied move) need past report dates as well.

None of the connected providers can fill this: a live check on 17 November 2026 showed that the LSEG account has neither the DataGrid scope (`TR.*` fields) nor the Estimates scope and its Search API carries no earnings dates; Polygon/Massive answers 403 for Benzinga earnings on the current plan; Schwab only exposes snapshot ratios; IBKR's TWS API offers earnings dates only through Wall Street Horizon (`reqWshEventData`, separate research subscription), and its `reqFundamentalData` (`CalendarReport`, `RESC`) is deprecated Refinitiv data. Monthly data subscriptions are not wanted; free or pay-per-request providers are. Verified with a free key on 17 November 2026: Alpha Vantage delivers the announced upcoming earnings of the US market in one CSV request (`EARNINGS_CALENDAR`, 1,010 rows for twelve months) and the full quarterly history per symbol with report date, release time, EPS estimate, actual and surprise (`EARNINGS`, 123 quarters for AAPL); on the same key it delivers the latest 100 daily bars, the full weekly history and an end-of-day quote. Financial Datasets bills USD 0.02 per request without subscription and delivers earnings history with the exact SEC filing time, end-of-day prices of any range, company facts and (in a following change) fundamentals.

## What Changes

- New provider capability **earnings** (`BaseEarningsProvider`) with a batch-first method: earnings events for a list of symbols and a date range. It is independent of the company capability, so other providers can add it later, including pay-per-request providers.
- New model `EarningsEvent`: canonical symbol, report date, release time (`bmo`, `amc`, `during`, `unknown`), date certainty as stated by the provider (`confirmed`, `projected`, `unknown`), whether it is reported, optional fiscal period end, EPS estimate, actual and surprise, currency, provider. MDH never estimates or extrapolates a date.
- New provider **Alpha Vantage** (`alphavantage`, free key) implementing the earnings capability (market-wide announced calendar from `EARNINGS_CALENDAR`, per-symbol history from `EARNINGS`) and the price capability (`1d` bars of the latest 100 trading days, full `1w` history, end-of-day last price; bars unadjusted), API key in the encrypted key store, connection test, detection of Alpha Vantage's HTTP-200 throttle and premium notices.
- New provider **Financial Datasets** (`financialdatasets`, USD 0.02 per request) implementing earnings history (report date and release window from the SEC filing, actual EPS, no estimates), `1d`/`1w` prices of any range, a last-price snapshot and the company profile from company facts. Earnings providers declare whether they deliver upcoming events; `GET /earnings/next` answers 501 for those that do not.
- **Request budgets for metered providers**: connection settings `request_budget_per_day` and `request_budget_per_month` with counters shared across replicas through Redis, refusal before the provider is called (`PROVIDER_QUOTA_EXHAUSTED`), usage endpoint and display in the Admin UI. Alpha Vantage defaults to its free-tier limit (25 per day, shared by prices and earnings); Financial Datasets defaults to 1,000 per month (USD 20) as a cost cap.
- New endpoints:
  - `GET /earnings/calendar?symbols=…&from=…&to=…` — events of up to 50 symbols in a range.
  - `GET /earnings/next?symbols=…` — the next announced event per symbol, or `null` with a per-symbol status (`ok`, `none_scheduled`, `not_applicable` for ETFs, `error`), plus the last stored reported event.
  - `GET /companies/{symbol}/earnings?from=…&to=…` — past and upcoming events of one stock.
- Earnings events are stored in the optional PostgreSQL store (`DATABASE_URL`): the market-wide upcoming calendar is refreshed at most once per `EARNINGS_CALENDAR_RESYNC_HOURS` (24 h) for all symbols together, per-symbol history when it is missing and after a symbol has reported. Stored events are served with `meta.stale = true` when the provider fails or the budget is exhausted. Without `DATABASE_URL` the parsed calendar is kept in Redis and history is fetched per request through the response cache.
- Response caching for the three endpoints with a new runtime cache policy `cache_ttl_earnings_seconds` (default 21600 s), admin cache scope `earnings`.
- New system default `default_earnings_provider`, an `earnings` category in the capabilities API, an `Earnings` capability chip and a default dropdown in the Admin UI.
- MCP tools `get_earnings_calendar` and `get_next_earnings`.

## Capabilities

### New Capabilities
- `earnings-calendar`: earnings event model, provider capability, calendar/next/company endpoints with per-symbol status, storage and refresh policy, stale serving, MCP tools.
- `alphavantage-provider`: Alpha Vantage integration for earnings (calendar and history) and prices, credentials, connection test, symbol translation, error detection and request budgets for metered providers.
- `financialdatasets-provider`: Financial Datasets integration for earnings history, prices and company profile on pay-per-request billing.

### Modified Capabilities
- `system-defaults`: new `default_earnings_provider` setting; the capabilities API lists an `earnings` category.
- `response-caching`: new earnings cache policy key and caching rules for the earnings endpoints.
- `provider-capabilities-display`: providers with the earnings capability show an `Earnings` chip.

## Impact

- **Code**: `app/providers/base.py` (`BaseEarningsProvider`), new `app/providers/alphavantage.py`, `app/providers/financialdatasets.py`, `app/providers/request_budget.py` (shared budget counter), `app/models/earnings.py`, `app/services/earnings_service.py`, `app/api/routes_earnings.py` and a route in `routes_companies.py`, `app/providers/registry.py`, `app/api/routes_admin.py` (credential allowlist, capabilities, usage), `app/admin/provider_config_repository.py` (`KNOWN_PROVIDERS`, budget settings), `app/cache.py`, `app/api/mcp.py`, `app/store/` (models, Alembic migration `0003`, repository), `app/observability/metrics.py`, Admin UI.
- **Dependencies**: `jsonschema` as a development dependency for the Financial Datasets contract test; no new runtime dependency.
- **Costs**: none with Alpha Vantage alone. With 100 symbols: one calendar request per day plus about 100 history requests spread over the first days (25 per day) and about 35 per month afterwards (one per symbol and report). Financial Datasets only when enabled: USD 0.02 per request, capped by its monthly budget.
- **API**: additive. VisioTrade can fill `earningsDate`, `daysToEarnings` and `earningsSource` from `GET /earnings/next` (change in the VisioTrade repository).
- **Not covered**: an IBKR earnings implementation (Wall Street Horizon subscription required; can be added behind the same capability), fundamentals snapshot, financial statements, analyst estimates and dividends (following change with Financial Datasets and LSEG Search), Alpha Vantage intraday, full daily history and adjusted bars (premium), estimated dates for companies that have not announced theirs, earnings for ETFs, indices and futures, non-US listings, a background scheduler, history of report-date changes, persisted per-provider symbol mapping and the history-store maintenance view (separate follow-up change).
