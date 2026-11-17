## Context

MDH has no earnings data. `CompanyProfile` holds name, exchange, sector and employees; news articles carry a keyword-based `category=earnings`. The consumer that needs earnings is VisioTrade:

- `GET /api/v1/watchlists/{id}/overview` returns `earningsDate`, `daysToEarnings` per row and `earningsSource` (`Literal["unavailable"]`) for up to 25 symbols; the spec requires that no estimated dates are returned.
- The Premium Put/Call Credit Spread filters (DTE 35–50) say that earnings are not checked.
- Trade analytics want past report dates (positions held through earnings, correlations without earnings windows, realised versus implied move — MDH already stores daily bars and IV points).

Provider situation, verified on 17 November 2026:

| Source | Upcoming dates | History | Cost model | Notes |
|---|---|---|---|---|
| LSEG | no | no | licence in place | Lacks DataGrid and Estimates scopes; Search has no dates. |
| Polygon/Massive | no | no | current plan | Benzinga earnings: 403 not entitled. |
| IBKR (TWS API) | only via Wall Street Horizon | deprecated path only | extra subscription | See "IBKR" below. |
| Schwab | no | no | — | Quote fundamentals only. |
| Finimpulse | yes | yes | subscription | Rejected: monthly plans, Basic/free without fundamentals. |
| Financial Datasets | no | yes (SEC filing time, actuals) | pay per request: USD 0.02 (x402 terms in `PAYMENT-REQUIRED`: 20000 USDC base units on Base), or prepaid credit from USD 20 | No estimates, no upcoming dates; EOD prices of any range (`day`, `week`), price snapshot, company facts, statements and metrics (fundamentals change). Header `X-API-KEY`; without key HTTP 402. |
| Alpha Vantage | announced dates, whole market in one request | yes, full quarterly history | free key (about 25 requests per day); premium is a subscription | See the spike results below. |

IBKR over the TWS API (checked 17 November 2026 against `ib_async` 2.1.0, IBKR's documentation and live against the paper account's IB Gateway 10.45, read-only, `tmp/ibkr_earnings_probe.py`, raw answers in `tmp/ibkr_earnings_probe_out/`):

- `reqFundamentalData(contract, reportType)` still exists in `ib_async` with `CalendarReport` (company calendar), `RESC` (analyst estimates), `ReportsFinSummary`, `ReportsFinStatements`, `ReportSnapshot`, `ReportsOwnership`. IBKR marks it legacy/deprecated, it delivers Refinitiv XML and needs a fundamentals data subscription; community reports say newer API versions refuse it. Not a basis for a new feature.
- `reqWshMetaData` / `reqWshEventData` (Wall Street Horizon) deliver earnings dates, dividends, splits and other corporate events as JSON, filterable by `conId`, watchlist or portfolio. IBKR's documentation requires the "Wall Street Horizon Enchilada Pro" research subscription (historically about USD 250 per month).
- Generic tick 456 (IB dividends: last 12 months, next 12 months, next date and amount) is IBKR's own data and needs no extra subscription — relevant for the dividends part of the fundamentals change, not for earnings.

- Live result: `reqWshMetaData` → error 10276 "News feed is not allowed"; `reqFundamentalData` `CalendarReport`, `RESC`, `ReportSnapshot`, `ReportsFinSummary` → error 10358 "Fundamentals data is not allowed"; generic tick 258 → 10358. Generic tick 456 works (AAPL: past 12 months 1.07, next 12 months 1.11, next 2027-02-08 at 0.27; JPM next 2027-01-06 at 1.65).
- The gateway warns (2172) that version 1045.1 is desupported on 2026-12-15 and 1050.1 becomes the minimum; reports say 10.50 no longer serves `reqFundamentalData`.

Decision: no IBKR earnings implementation in this change. The capability is provider-neutral, so an `IBKRProvider` earnings implementation over WSH can be added if the subscription is booked. Tick 456 is a free dividends source for the fundamentals change.

Spike with a free Alpha Vantage key, 17 November 2026 (15 requests, raw responses in `tmp/alphavantage_spike_out/`):

- `EARNINGS_CALENDAR` (no symbol): `3month` 771 rows (2026-11-17 … 2027-02-15), `12month` 1,010 rows (… 2027-05-27); only USD. It lists **announced dates only**: AAPL, MSFT, GOOGL, META, AMZN and TSLA (late-January reporters that have not announced) are missing, JPM (announced 2027-01-14) is present. `timeOfTheDay`: empty 531, `pre-market` 135, `post-market` 105; `estimate` empty in 311 rows. Share classes in dot notation (`BF.B`, `LEN.B`, `HEI.A`), preferred shares as `JPM-PD`, `KEY-PL`.
- `EARNINGS`: AAPL 123 quarters back to 1996 with `reportTime` `post-market`/`pre-market`; 30 values `None`. `BRK-B` works, `BRK.B`, `SPY` and an unknown ticker return `{}`.
- Prices: `TIME_SERIES_DAILY` compact = latest 100 trading days (US/Eastern dates); `outputsize=full`, `TIME_SERIES_DAILY_ADJUSTED`, `TIME_SERIES_INTRADAY` and `OVERVIEW` answer "premium". `TIME_SERIES_WEEKLY` returns 1,411 weeks since 1999, the running week dated with its latest day, **not split-adjusted** (AAPL 499.23 → 120.96 across the 2020 split). `GLOBAL_QUOTE` returns the last close with `latest trading day`. SPY works for prices.
- No throttle notice within 15 requests; the daily limit and its reset time remain to be observed in operation.

Follow-up probe on 17 November 2026 (`tmp/alphavantage_limit_probe.py`, raw
responses in `tmp/alphavantage_limit_probe_out/`): the first `GLOBAL_QUOTE`
request succeeded; the second, less than a second later, returned HTTP 200 with
`Information`: "Please consider spreading out your free API requests more
sparingly (1 request per second)". The same notice also mentions "25 requests
per day" and "premium endpoints". Only a `Date` header was present, with no
`Retry-After` or reset header. Recorded as
`tests/fixtures/alphavantage/burst_limit.json`. This is evidence of burst
throttling, not daily exhaustion. User decision: only an explicit daily-quota
notice exhausts the day counter; burst throttles are handled separately. The
25/day default and New York budget boundary remain as planned; the upstream
daily limit and reset time will be verified in the final integration checks.

The optional PostgreSQL store (`market-history-store`, `app/store/`) exists with request-driven synchronisation, fail-open behaviour and Alembic migrations at startup. The Redis response cache (`app/cache.py`) has runtime-configurable policies and admin scopes.

## Goals / Non-Goals

**Goals:**
- A provider-neutral earnings capability and model that a second provider can implement without API changes.
- The next earnings date for a watchlist of 25 symbols in one MDH request, without one provider request per symbol.
- Report dates and EPS results of the past years per stock, for analytics.
- Provenance on every event: provider, date certainty, data age.
- No subscription: the free Alpha Vantage tier suffices for daily use. A metered provider can never exceed a configured request budget.
- MDH keeps running without PostgreSQL and without an Alpha Vantage key.

**Non-Goals:**
- Fundamentals snapshot, financial statements, analyst estimates and revisions, dividends (following change).
- Earnings for ETFs, indices, futures and non-US listings.
- A background scheduler; synchronisation is request-driven like the history store.
- Recording the history of report-date changes.
- A persisted per-provider symbol mapping table and the history-store maintenance view (separate follow-up change).
- Merging fields from several providers into one event.
- Billing in currency units; budgets count requests.

## Decisions

### D1: Separate `earnings` capability with a batch-first method

```python
class BaseEarningsProvider(ABC):
    name = "none"
    async def get_upcoming_earnings(self, start: date, end: date, roots: list[str] | None) -> list[EarningsEvent]: ...
    async def get_earnings_history(self, root: str) -> list[EarningsEvent]: ...
    async def test_connection(self) -> dict[str, Any]: ...
```

Two methods because providers split the data this way: an upcoming calendar that is cheap for many symbols at once (Alpha Vantage: whole market in one request; `roots=None` means "all the provider has") and a per-symbol history. The registry gets `default_earnings_provider`, `use_earnings_provider(name)` and an `earnings` entry in `list_available_providers`.

*Alternatives:* one `get_earnings_events(roots, start, end)` (hides the very different cost of the two parts from the service, which then cannot plan requests); methods on `BaseCompanyProvider` (LSEG, IBKR and Polygon cannot implement them).

### D2: `EarningsEvent` keeps date certainty and reporting state apart

| Field | Type | Meaning |
|---|---|---|
| `symbol` | str | canonical symbol |
| `report_date` | date | announcement date |
| `report_time` | `bmo` \| `amc` \| `during` \| `unknown` | Alpha Vantage `pre-market`→`bmo`, `post-market`→`amc`, empty → `unknown`; Financial Datasets `filing_window` `PRE_MARKET`/`POST_MARKET`/`MARKET_HOURS` → `bmo`/`amc`/`during` |
| `date_status` | `confirmed` \| `projected` \| `unknown` | only what the provider states; Alpha Vantage states nothing for upcoming dates → `unknown` (its calendar observably holds announced dates only, but does not say so); reported events → `confirmed` |
| `reported` | bool | `report_date` before today (New York) or an actual EPS is present |
| `fiscal_period_end` | date \| null | `fiscalDateEnding` |
| `eps_estimate`, `eps_actual`, `eps_surprise`, `eps_surprise_pct` | Decimal \| null | surprise in percent as delivered |
| `currency` | str \| null | currency of the EPS values |
| `provider` | str | provider that delivered the event |
| `updated_at` | datetime | when MDH last received this event |

VisioTrade's rule "never estimated" is a client decision on `date_status`; MDH delivers the information and does not decide.

### D3: Alpha Vantage requests

- Upcoming: `function=EARNINGS_CALENDAR&horizon=3month` (CSV) without `symbol` returns all US issuers with an announced date. One request per refresh covers every symbol. A requested range beyond three months uses `horizon=6month` or `12month`. A company that has not announced its date has no row; `next` reports `none_scheduled` together with the last reported event, and MDH does not project a date from the previous year.
- History: `function=EARNINGS&symbol=<root>` (JSON) per symbol; `quarterlyEarnings` become reported events.
- An upcoming event from the calendar and a reported event from the history for the same symbol and `fiscal_period_end` are the same event; the history entry wins once it has `reportedEPS`.
- Responses with an `Information`, `Note` or `Error Message` field are errors (D7), not empty data.

*Alternatives:* per-symbol calendar requests (`symbol=` parameter; 25 requests for 25 symbols would exhaust the free tier in one overview).

### D4: Storage

New tables (migration `0003`):

- `earnings_sync`: one row per (`provider`, `scope`), where `scope` is `calendar` or a canonical symbol; `covered_from`, `covered_to`, `synced_at`, `sync_failed_at`.
- `earnings_events`: primary key (`provider`, `symbol`, `report_date`); all fields of D2; `source` (`calendar` | `history`), `first_seen_at`, `updated_at`.

A calendar synchronisation replaces, in one transaction, all `source = calendar` events of the provider in the covered range with the returned ones, so a moved report date replaces the old row. A history synchronisation upserts the symbol's reported events and deletes its `calendar` events whose `fiscal_period_end` is now reported. Events of different providers are never mixed.

*Alternatives:* key on fiscal period (the calendar's `fiscalDateEnding` is reliable, but moving the key away from the date makes range reads harder; the date key with replace-by-source handles moves); storing only watchlist symbols from the calendar (the whole calendar is a few thousand rows and makes every later `next` request free).

### D5: Request-driven refresh policy

- **Calendar**: refreshed when its `synced_at` is older than `EARNINGS_CALENDAR_RESYNC_HOURS` (24) or the requested range exceeds `covered_to`. One request for all symbols.
- **History of a symbol**: fetched when the symbol has no history sync and a request needs dates before today, or when the symbol has a stored event dated within the last `EARNINGS_ACTUALS_WINDOW_DAYS` (10) without `eps_actual` and its history was synced more than 12 h ago. `GET /earnings/next` never triggers history requests.
- After a failed synchronisation the scope is not retried for `EARNINGS_RETRY_MINUTES` (30); stored events are served meanwhile.
- When the budget does not allow all due history requests, the symbols are served in request order until the budget is used; the rest get their stored or calendar-only events and `meta.symbols[].history` = `pending`.

Cost with 100 watched symbols: one calendar request per day, about 100 history requests once (four days at 25 per day), then about one per symbol and quarter.

### D6: Without the store

When `DATABASE_URL` is unset or the store is failing open, the parsed calendar is cached in Redis under `mdh:earnings:provider-calendar:<provider>:<horizon>` for `EARNINGS_CALENDAR_RESYNC_HOURS`, and per-symbol history goes through the response cache of `GET /companies/{symbol}/earnings`. Without Redis either, every request calls the provider within the budget. `meta.stale` is never set in this mode.

### D7: Request budgets for metered providers

A reusable `RequestBudget` (`app/providers/request_budget.py`) for any provider whose plan is metered, shared by all capabilities of the provider. Connection settings `request_budget_per_day` and `request_budget_per_month` (integers ≥ 0, `0` = no limit) are read from the provider's runtime config; Alpha Vantage defaults to 25 per day and no monthly limit, Financial Datasets to no daily limit and 1,000 per month. Before every upstream request the budget increments Redis counters `mdh:quota:<provider>:d:<YYYY-MM-DD>` and `…:m:<YYYY-MM>` (day in `America/New_York`, the upstream reset time to be confirmed in final integration checks; month in UTC) and refuses with `PROVIDER_QUOTA_EXHAUSTED` (HTTP 429, details `provider`, `period`, `budget`) when a counter would exceed its budget. Without Redis a process-local counter is used and the usage endpoint reports `shared: false`. A warning is logged once per period at 80 %. Only an explicit daily-quota notice from Alpha Vantage sets the day counter to the budget so further requests stop until the next day. Per-second/burst notices are classified before daily or premium keywords, handled with request pacing and bounded retry, and never exhaust the day counter. `GET /api/admin/providers/{name}/usage` returns the counters for metered providers; the Admin UI shows them in the provider details. A Prometheus counter `mdh_provider_upstream_requests_total{provider}` counts requests.

*Alternatives:* relying on the provider's own throttle (Alpha Vantage answers HTTP 200 with a notice; a pay-per-request provider would simply bill); per-provider ad-hoc counters (every metered provider needs the same).

### D8: Symbols and instrument types

Earnings apply to `stock` only. In the batch endpoints an ETF row is `not_applicable` without a provider call; index, future and option symbols are rejected with 422. `GET /companies/{symbol}/earnings` for an ETF returns 422 `CAPABILITY_NOT_SUPPORTED`. Alpha Vantage is inconsistent between functions: the calendar uses dot notation (`BF.B`), which equals the canonical symbol, while `EARNINGS` and the price functions need dash notation (`BRK-B`). Preferred-share rows (`-P` suffix) are dropped from the calendar. The hub cannot tell an ETF from a stock by its symbol (bare symbols parse as `stock`; `etf` only comes from an explicit `sec_type`), so the service treats an explicit `sec_type=etf` and a maintained list of well-known ETF tickers (`KNOWN_ETFS` in `earnings_service.py`) as ETFs; an unlisted ETF is not special-cased and simply has no earnings data at the provider (`none_scheduled` / `not_found`). `GET /companies/{symbol}/earnings` for an ETF is HTTP 422 with code `CAPABILITY_NOT_SUPPORTED` (`details.http_status = 422`), whereas a provider without upcoming support answers 501 with the same code.

### D9: API shape

- `GET /earnings/calendar?symbols=AAPL,MSFT&from=2026-11-01&to=2027-02-28&provider=` → `ResponseEnvelope[list[EarningsEvent]]` sorted by `report_date`, then symbol. Defaults `from` = today − 30 days, `to` = today + 90 days; at most 50 symbols and 800 days (422 otherwise). `meta.symbols` lists per symbol `status` (`ok`, `not_applicable`, `not_found`, `error`), `history` (`complete`, `pending`, `not_requested`) and `message`.
- `GET /earnings/next?symbols=…` → `ResponseEnvelope[list[NextEarnings]]`, one row per requested symbol in request order: `symbol`, `event` or `null`, `days_until` (calendar days from today in New York), `last_reported` (latest stored reported event or `null`; never fetched for this endpoint), `status` (`ok`, `none_scheduled`, `not_applicable`, `error`), `message`. Served from the calendar only. A symbol absent from a successfully loaded calendar is `none_scheduled`.
- `GET /companies/{symbol}/earnings?from=…&to=…` → events of one stock, defaults `from` = today − 1095 days, `to` = today + 400 days. Unknown symbol → 404.
- All carry `meta.provider`, `meta.data_as_of` (oldest synchronisation time of the involved scopes, or the provider call time) and `meta.stale`. CSV export via `format=csv` for calendar and company earnings.

### D10: Caching

Keys `mdh:earnings:calendar:…`, `mdh:earnings:next:…`, `mdh:companies:earnings:…` with the symbol list normalised (upper case, de-duplicated, sorted); `next` restores the request order after the cache. `from`/`to` are day-granular. Stale responses are not cached. Admin cache scope `earnings` clears all three and the provider calendar keys of D6.

### D11a: Alpha Vantage prices

`native_intervals = {1d, 1w}`, `price_sec_types = price_history_sec_types = {stock, etf}`. Daily bars come from the compact `TIME_SERIES_DAILY` (latest 100 trading days): a longer range returns what exists, and with the history store enabled the stored series grows with every tail synchronisation, so the window widens over time. Weekly bars come from `TIME_SERIES_WEEKLY` with full history; the running week's row is dated with its latest day and is mapped to the canonical week bucket like other providers' weekly bars. The last price is the end-of-day `GLOBAL_QUOTE` with the close of `latest trading day` as its time. Bars are unadjusted; the admin provider details state `price_adjustment: "none"` and MDH does not adjust. Prices and earnings share one budget of 25 requests per day, so Alpha Vantage is meant as an explicitly requested or fallback price provider, not as the default for VisioTrade's daily scans.

*Alternatives:* deriving `1d` from weekly bars (impossible); adjusting with split data from another source (premium data or a second provider for a free fallback — not worth it).

### D11b: Financial Datasets

Pay per request (USD 0.02), one budget for all its capabilities, default 1,000 requests per month. It is implemented without an API key against a pinned copy of the published OpenAPI document; fixtures are schema-conformant responses and a contract test validates fixtures and built requests against the pinned schema. Live verification follows once a key with credit exists. `earnings_upcoming = False`: it contributes reported events with the SEC filing time as report time (earliest 8-K per `report_period`, the earnings press release, else the earliest filing) and actual EPS, but no estimates. `filing_window` enum from the schema: `PRE_MARKET` (04:00–09:30 ET), `DURING_MARKET`, `AFTER_HOURS` (outside regular hours, so the filing time decides between `amc` and `bmo`), `WEEKEND`. The schema does not say whether prices are adjusted → `price_adjustment: "unknown"`. Prices: `GET /prices` with `interval=day|week` for any range in one paginated request, and `GET /prices/snapshot` as last price. Company profile from `GET /company/facts`; no company search. Without a key or with exhausted credit it answers 402, mapped to `PROVIDER_NOT_AVAILABLE`. x402 per-call payment is not used (needs a wallet). The fundamentals endpoints (`/financials/*`, `/financial-metrics/snapshot`) follow in the fundamentals change.

### D11: MCP tools

`get_earnings_calendar(symbols, from_date, to_date, provider)` and `get_next_earnings(symbols, provider)` call the same service and policy as HTTP.

## Risks / Trade-offs

- [Free tier limit changes or the key is throttled earlier than the local budget] → only explicit daily-quota notices set the day counter to the budget (D7); burst throttles use pacing and bounded retry; calendar requests are one per day, so `next` keeps working from the store.
- [Alpha Vantage gives no confirmation flag] → `date_status` is `unknown` for upcoming events; the field stays in the model for providers that have one. VisioTrade decides whether to show unconfirmed dates.
- [Calendar dates move between daily refreshes] → refresh every 24 h replaces calendar rows; data age is visible in `meta.data_as_of`.
- [History backfill of a large watchlist takes several days on the free tier] → `next` does not depend on history; `meta.symbols[].history = pending` makes the gap visible.
- [Free-tier terms (personal use)] → acceptable for the current deployment; the provider is replaceable behind the capability.
- [Alpha Vantage price requests use up the earnings budget] → shared budget is explicit; Alpha Vantage is not configured as default price provider; history store and response cache absorb repeats.
- [Unadjusted Alpha Vantage bars across a split distort returns and correlations] → `price_adjustment: none` in the admin details and documentation; clients that compute returns over long ranges use an adjusting provider.
- [Financial Datasets credit runs out] → monthly budget below the credit; 402 maps to a clear `PROVIDER_NOT_AVAILABLE`; stored data is served stale.
- [Budget counter lost when Redis restarts] → at most one extra day's budget; Alpha Vantage's own throttle remains the backstop.

## Migration Plan

Additive. Migration `0003` creates two tables and runs at startup under the existing advisory lock. Without an Alpha Vantage key the provider is not enabled and the earnings endpoints answer 503 "No earnings provider configured". Rollback: disable the provider; the tables can stay.

## Open Questions

- Alpha Vantage free-tier daily limit, its reset time and the exact throttle text (not reached in the spike).
- Financial Datasets (until a key exists): whether prices are adjusted, ETF coverage of `/prices`, whether every quarter has an 8-K with the earnings release — implemented defensively per schema, verified in task 9.
