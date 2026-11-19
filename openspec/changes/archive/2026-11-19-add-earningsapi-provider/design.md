## Context

The earnings capability (change `add-earnings-calendar`, archived 2026-11-17) assumes two kinds of provider requests: one market-wide calendar request for a date range (`get_upcoming_earnings`) and one history request per symbol for reported events (`get_earnings_history`). `GET /earnings/next` is answered from the calendar only and never requests history. Providers without a calendar set `earnings_upcoming = False` and get 501 from `/earnings/next`.

On `market-data-hub.framas.cloud` (version 1.5.1, checked 2026-11-18) only Financial Datasets is enabled as earnings provider, Alpha Vantage is not configured and `default_earnings_provider` is unset:

| Request | Result |
|---|---|
| `/earnings/next?symbols=AAPL&provider=financialdatasets` | 501 `CAPABILITY_NOT_SUPPORTED` |
| `/earnings/next?symbols=AAPL` | 503 `PROVIDER_NOT_AVAILABLE` |
| `/earnings/calendar?symbols=AAPL&provider=financialdatasets` | 200, reported event of 2026-11-02 only |
| `/earnings/next?symbols=AAPL&provider=alphavantage` | 400 `INVALID_PROVIDER` |

EarningsAPI, documented at `https://www.earningsapi.com/docs`, `/docs/earnings` and `/docs/calendar-earnings`:

| Item | Value |
|---|---|
| Base URL, auth | `https://api.earningsapi.com`, query parameter `apikey` |
| Company earnings | `GET /v2/earnings?symbol=<root>` (`symbol` required): JSON array, newest first, upcoming and reported quarters; fields `date`, `symbol`, `name`, `time`, `epsEstimate`, `eps`, `revenue`, `revenueEstimate`; `time` is `time-pre-market`, `time-after-hours` or `null` |
| Earnings calendar | `GET /v2/calendar/earnings?date=<YYYY-MM-DD|today|yesterday|tomorrow>` (one date, New York time): object `{date, pre: [...], after: [...], notSupplied: [...]}`, entries with `symbol`, `name`, `epsEstimate`, `eps`, `revenue`, `revenueEstimate` |
| Free tier | 60 requests per minute, 100 per day, 1,000 per month, reset in New York time; most recent 24 months of history (data from 2018-01-01 on Pro); values for today and later updated once daily; unavailable values are `null`, never `0` |
| Error formats | not documented (examples only call `raise_for_status()`) |

Sample response of `/v2/earnings?symbol=ADI` (2026-11-18, provided by the user), nine quarters back to 2024-11-26:

```json
[{"date": "2026-11-24", "symbol": "ADI", "name": "Analog Devices, Inc.", "time": "time-pre-market",
  "epsEstimate": 3.884015, "eps": null, "revenue": null, "revenueEstimate": 4320121322},
 {"date": "2026-08-19", "symbol": "ADI", "name": "Analog Devices, Inc.", "time": "time-pre-market",
  "epsEstimate": 3.337451, "eps": 3.45, "revenue": 4021899000, "revenueEstimate": 3925805875},
 {"date": "2026-02-18", "symbol": "ADI", "name": "Analog Devices, Inc.", "time": null,
  "epsEstimate": 2.307225, "eps": 2.46, "revenue": 3160263000, "revenueEstimate": 3117530725}]
```

No fiscal period end, no currency, no confirmation flag in either endpoint.

## Goals / Non-Goals

**Goals:**
- Upcoming report dates for VisioTrade's watchlist without a subscription.
- Near-term dates and fresh actuals for every symbol at a cost independent of the watchlist size.
- Stay inside 100 requests per day and 1,000 per month for a watchlist of about 100 stocks.
- Let clients ask for upcoming or reported events only.
- Keep the existing endpoints, statuses and store semantics; add only what EarningsAPI's request shapes need.

**Non-Goals:**
- Forward EPS consensus per fiscal year (forward P/E); EarningsAPI only has the next quarter's estimate. A later fundamentals/estimates change.
- History backfill through the day calendar, market-holiday awareness of the window.
- Estimating report dates, merging events of different providers, a background scheduler.

## Decisions

### D1: Two earnings interfaces, one capability each

MDH derives capabilities from the interfaces a provider implements and resolves each capability through its own default. Earnings follow that pattern with two interfaces:

- `BaseEarningsHistoryProvider` → capability `earnings_history`: `get_earnings_history(root)`.
- `BaseEarningsUpcomingProvider` → capability `earnings_upcoming`: `upcoming_mode` `calendar` (`get_upcoming_earnings(start, end, roots)`) or `symbol` (`get_symbol_earnings(root)`, upcoming and reported in one request), optionally `earnings_day_calendar` with `get_earnings_for_date(day)`.

Both derive from `BaseEarningsProvider`, so the existing catalog key `earnings` stays as the union for current clients. `upcoming_mode` is an internal strategy of the upcoming interface for the planner, not a capability.

| Provider | `earnings_upcoming` | `earnings_history` |
|---|---|---|
| Alpha Vantage | yes, mode `calendar` | yes |
| Financial Datasets | no | yes |
| EarningsAPI | yes, mode `symbol` + day calendar | yes (same request as `get_symbol_earnings`) |

*Alternative*: one interface with a flag `earnings_upcoming_source` (`calendar`/`symbol`/`none`). Rejected: a flag hides the capability from the registry and the catalog, needs special cases in validation and admin, and does not allow choosing a provider per role, which is how every other capability in MDH works.

*Alternative*: wrap both EarningsAPI endpoints into `get_upcoming_earnings(start, end, roots)`. Rejected: the service calls it with `roots=None` for a 365-day range (365 requests), and the planner would not see the per-day and per-symbol costs.

### D2: Day-calendar window

For providers with a day calendar the service maintains the window from the previous weekday through `EARNINGS_DAY_CALENDAR_WEEKDAYS` (default 7) weekdays after today, weekdays only. A day is due when

1. it has no successful synchronisation, or
2. it is the previous weekday, today or one of the next two weekdays and its last successful synchronisation is older than 20 hours,

and it is not in the `EARNINGS_RETRY_MINUTES` pause after a failure. Due days are fetched in date order before any per-symbol request and only when the request reaches into the window (`/earnings/next` always does). Steady state per weekday: previous weekday, today, two next weekdays, one new day at the end = 5 requests, about 110 per month. The previous weekday's refresh collects the actuals of its after-hours reports.

### D3: Per-symbol refresh plan

For `symbol` providers a requested stock is due when

1. it has no successful synchronisation and the request needs its past (calendar or company endpoint reaching before today with `kind` `all` or `reported`), or needs its next event and the day-calendar window holds no event of the stock on or after today; or
2. it has no stored event on or after today, and its last successful synchronisation is before its latest stored report date (the report happened: fetch the next quarter, once per quarter) or older than `EARNINGS_SYMBOL_RESYNC_DAYS` (default 7, only while the company has not announced its next date); or
3. a day-calendar synchronisation invalidated it (D4); or
4. the request does not use a day calendar (the provider has none, or the request does not reach into the window: `kind=reported`, history role of a composed response), a stored event dated today or within the last `EARNINGS_ACTUALS_WINDOW_DAYS` has no `eps_actual` and the last synchronisation is older than 12 hours;

and it is not in the retry pause. Only rule 1 depends on what the request needs; rules 2–4 also apply to requests for reported events only. Due symbols are fetched in request order within the remaining budget; the rest are pending: stored events are served with `meta.stale = true`, symbols without stored events get `status: "error"` and the message `provider request budget exhausted`.

A stock with a known next date is never resynchronised per symbol for its age: a move of that date is caught by the day-calendar window (the new date's day sync deletes the old event, a removed event invalidates the symbol). The per-symbol endpoint is therefore needed about once per quarter and symbol, plus weekly checks while a company has not announced its next date.

Budget for 100 symbols: about 100 requests for the first synchronisation (one day); afterwards about 100 per quarter after the reports (≈ 35 per month) plus the weekly checks for symbols without an announced date (task 0.2 records whether EarningsAPI lists the next date right after a report; if it does, these checks almost vanish; at most ≈ 130 per month), plus about 110 day-calendar requests: about 150–280 per month. Consumers (VisioTrade, TradeSensei) may call MDH as often as they like; upstream requests depend only on these rules.

*Alternative*: a blanket weekly per-symbol resync (≈ 430 requests per month for 100 symbols). Rejected: the day window already catches moves. *Alternative*: per-symbol only (no day calendar). Rejected: date moves in the last days before a report go unnoticed for up to 7 days, and every report needs an extra per-symbol request for the actuals.

### D4: Store semantics

Existing tables are reused. Day synchronisations are sync rows with scope `calendar-day:YYYY-MM-DD` and `covered_from = covered_to = day`; the sync table gets a nullable `invalidated_at` column.

- **Day sync** (one transaction, advisory lock on the day scope): delete all events of the provider dated that day regardless of source; insert the day's events with source `calendar`; for every symbol in the day, delete the provider's unreported events of that symbol dated today or later, within 60 days of the day and not on it; for every symbol that had an event on that day before and has none now, set `invalidated_at` on its symbol sync row.
- **Symbol sync** of a `symbol` provider: insert or update all returned events with source `history`; delete the provider's stored events of the symbol dated today or later that are not in the response; clear `invalidated_at`.

The latest synchronisation wins. Calendar providers keep their range replacement unchanged.

Without the store, day results are cached in Redis under `mdh:earnings:provider-day:{provider}:{date}` (TTL 7 days) and symbol results under `mdh:earnings:provider-symbol:{provider}:{root}` (TTL `EARNINGS_SYMBOL_RESYNC_DAYS`), each with its synchronisation time; the same due rules apply, invalidation is not tracked.

### D5: EarningsAPI mapping

| EarningsAPI | `EarningsEvent` |
|---|---|
| `date` (per-symbol) or requested date (calendar) | `report_date` |
| per-symbol `time`: `time-pre-market` / `time-after-hours` / `null` or other | `bmo` / `amc` / `unknown` |
| calendar group: `pre` / `after` / `notSupplied` | `bmo` / `amc` / `unknown` |
| `epsEstimate`, `eps` | `eps_estimate`, `eps_actual` (`Decimal(str(x))`, `null` or non-finite → `null`) |
| computed | `eps_surprise = eps − epsEstimate`, `eps_surprise_pct = surprise / |epsEstimate| × 100` when both present and the estimate is not 0 |
| `revenueEstimate`, `revenue` | `revenue_estimate`, `revenue_actual` |
| — | `fiscal_period_end: null`, `currency: "USD"`, `date_status`: `confirmed` when reported, else `unknown` |
| `symbol` | per-symbol: ignored, the requested canonical symbol is used; calendar: canonical form of the delivered symbol |

Reconciliation by `fiscal_period_end` does not apply (null); EarningsAPI's events are unique per symbol and date and are replaced by D4.

### D6: Errors, pacing and budget

`minimum_spacing = 1.0` s per process for the 60-per-minute limit, bounded retry on HTTP 429 with `Retry-After`. Budget defaults `request_budget_per_day = 100`, `request_budget_per_month = 1000`; the day counter uses New York time like EarningsAPI. HTTP 401/403 → `PROVIDER_NOT_AVAILABLE` (invalid key); a 429 or notice indicating the daily or monthly quota → `exhaust_day()` and `PROVIDER_QUOTA_EXHAUSTED`; an empty array or 404 for a symbol → `DATA_NOT_FOUND`; an empty day (all groups empty) is a valid empty result; other non-200 → `map_httpx_http_error`; an unexpected shape → `PROVIDER_ERROR`. The exact error bodies are recorded in task 0.1 before the mapping is finalised.

### D7: Symbols

Share classes are sent and parsed in the notation verified in task 0.1 (`BRK.B` or `BRK-B`). Day-calendar entries of non-US listings or ADRs (e.g. `ABEV`) are stored like any other symbol; ETFs are answered `not_applicable` by the existing rule without a provider call.

### D8: Revenue fields

`revenue_estimate` and `revenue_actual` are optional Decimals on `EarningsEvent`, two nullable `NUMERIC` columns in the earnings event table (same Alembic migration as `invalidated_at`), CSV columns after the EPS columns, included in the reconciliation (reported values win). Alpha Vantage and Financial Datasets leave them `null`.

### D9: `kind` filter

`GET /earnings/calendar` and `GET /companies/{symbol}/earnings` accept `kind` = `all` (default), `upcoming` (events on or after today in New York, `reported: false`) or `reported` (`reported: true`); MCP `get_earnings_calendar` gets the same optional argument. The filter is applied after composition and also feeds the planner: with `kind=upcoming` no history is requested from calendar providers and `meta.symbols[].history` is `not_requested`; with `kind=reported` no calendar or day calendar is requested. `/earnings/next` is unchanged; it is the forward view per symbol.

### D10: Role defaults and composed responses

Two system defaults, `default_earnings_upcoming_provider` and `default_earnings_history_provider`, replace `default_earnings_provider` (migrated once, still accepted as shorthand in the PUT). `/earnings/next` and `kind=upcoming` use the upcoming role, `kind=reported` the history role, `kind=all` both: unreported events only from the upcoming provider, reported events only from the history provider. The split is by the event's state, so the two sources never describe the same event twice, except on the report day itself (announced date vs. SEC filing date); an unreported event is dropped when the history provider has a reported event of the same symbol within 7 days. Every event keeps its `provider`; a composed response sets `meta.providers`. With one provider for both roles nothing changes. An explicit `provider` serves only the roles it implements.

The catalog publishes `available.earnings_upcoming`, `available.earnings_history`, `defaults.earnings_upcoming`, `defaults.earnings_history` and `defaults.earnings` (= upcoming default, currently missing). This fixes the reported VisioTrade error at its cause: VisioTrade validates its forward setting against `earnings_upcoming`, and a history-only provider such as Financial Datasets can still serve the history role (exact SEC filing times) without being asked for dates it cannot deliver.

*Alternative*: never combine providers, one default for both roles. Rejected after review with the user: it contradicts the capability-per-interface concept of MDH and forces the history role onto whichever provider delivers dates. The earlier concerns (different date sources, reconciliation) are handled by splitting by event state and the report-day rule.

## Risks / Trade-offs

- [Undocumented error formats] → spike before implementation (task 0.1), mapping fixed from recorded responses; unknown shapes map to `PROVIDER_ERROR`, never to an empty result.
- [Composed responses from two providers] → `last_reported` of `/earnings/next` comes from the history provider's store, so it matches Analyze; around the report day the 7-day rule removes the duplicate; EPS estimates of a history-only provider may be `null` while the upcoming event has one.
- [Report date moved from outside into the window] → caught by the day sync of the new date (deletes the old event within 60 days); moves between two dates outside the window are caught by the weekly resync.
- [Window contains market holidays] → one empty request per holiday; acceptable for now.
- [Calendar entries for symbols nobody requested] → stored rows grow by roughly 100–300 per weekday; covered by the existing store maintenance.
- [`/earnings/next` may now call the provider] → only for `symbol` providers and only for stocks the store cannot answer; calendar providers keep "at most one calendar request".
- [Shared key across replicas] → budget counters are shared through Redis; pacing is per process, so two replicas may reach 120 per minute; the 429 retry covers it.

## Migration Plan

Verification happens on a local deployment (task 5.4). Production rollout is an operator step after the release, outside this change:

1. Deploy the version with the migration (additive columns).
2. In the Admin UI of `market-data-hub.framas.cloud`: store the `api_key` for `earningsapi`, enable it, test the connection, set `default_earnings_upcoming_provider = earningsapi` and `default_earnings_history_provider` (`earningsapi`, or `financialdatasets` for SEC filing times).
3. Verify `GET /earnings/next?symbols=ADI,AAPL,SPY` and VisioTrade's watchlist; check usage after the first day.

Rollback: disable the provider and reset the default; the new columns stay unused.

## Spike findings (2026-11-19, task 0)

14 requests with the free key; raw responses in `tmp/earningsapi_spike_out/`, trimmed fixtures in `tests/fixtures/earningsapi/`.

- **Errors**: invalid key → HTTP 403, `Content-Type: text/html`, body `Invalid API Key` (no JSON). Unknown symbol and ETF (`SPY`) → HTTP 404 `{"error":"Symbol not found"}`. Quota and per-minute 429 bodies were not triggered (would cost the quota); the 429/quota mapping stays defensive: any 429 → bounded retry with `Retry-After`, then `PROVIDER_QUOTA_EXHAUSTED` if the `X-Daily-Remaining` or `X-Quota-Remaining` header is `0`.
- **Quota headers on every response** (also 404): `X-Daily-Limit/Used/Remaining/Reset` (reset `00:00Z`, i.e. UTC, not New York) and `X-Quota-Limit/Used/Remaining/Reset` (monthly), `X-Plan: free`. No `Retry-After` seen. Requests answered with 404 count against the quota. The budget can be reconciled from these headers.
- **Share classes**: `BRK.B` and `BRK-B` both work and both return `symbol: "BRK.B"`; the calendar also uses dots (`BF.A`). Dot notation is used.
- **ETF**: `SPY` → 404 (same as an unknown symbol).
- **Day calendar horizon**: populated for 2026-12-03 (2 weeks ahead, 41 entries), empty for 2026-12-17 (4 weeks) and 2027-01-14; a Saturday is an empty valid result. The default `EARNINGS_DAY_CALENDAR_WEEKDAYS = 7` is well inside the horizon and stays.
- **Budget reset**: the provider's daily counter resets at 00:00 UTC while MDH's request budget day follows New York time like the other metered providers; the difference (up to five hours) is covered by the `X-Daily-Remaining: 0` header on a 429, which exhausts the day.
- **Duplicates**: a day calendar can list a symbol twice (`DLTR` in 2026-11-24); the mapper keeps one event per symbol and date (first wins, `bmo`/`amc` preferred over `unknown`).
- **Agreement**: per-symbol and calendar values for ADI on 2026-11-24 agree (`epsEstimate 3.883769`, `revenueEstimate 4319898951`).
- **Next quarter right after a report**: not listed. `AAPL` (reported 2026-11-02) and `BRK.B` (2026-11-06) have no upcoming event. The weekly resync for symbols without an announced date is therefore required (D3 rule 2).
- Calendar entries carry no `date`, only the envelope `date`; actuals of the previous day are present (`eps` filled in `cal_yesterday`).

## Open Questions

- Error bodies and status codes for invalid key, unknown symbol, per-minute limit and exhausted quota (task 0.1).
- Share-class notation in both endpoints (task 0.1).
- How far ahead the day calendar is populated (task 0.1); the window size follows from it.
- ~~Whether VisioTrade's "forward earnings" means upcoming report events (covered by `kind=upcoming` and `/earnings/next`) or forward EPS consensus (not covered).~~ Upcoming report events; VisioTrade adopts `earnings_upcoming` (D10).
