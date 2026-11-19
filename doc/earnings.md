# Earnings Calendar

Earnings dates and results for **stocks**, through a provider-neutral `earnings` capability. Three providers are available, all disabled until you store a key and enable them in the Admin UI. None needs a subscription.

| Provider | Upcoming dates | History | Prices | Cost model |
|---|---|---|---|---|
| `alphavantage` | announced dates of the whole US market in **one** request | full quarterly history (report date, release time, EPS estimate/actual/surprise) | `1d` (latest 100 trading days), `1w` (full), end-of-day last price | free key, about **25 requests per day** (shared by prices and earnings) |
| `earningsapi` | announced dates per stock plus a market-wide **day calendar** (one request per day) | reported quarters of the last 24 months with EPS estimate/actual and **revenue estimate/actual** | – | free key, **100 requests per day / 1,000 per month**, 60 per minute |
| `financialdatasets` | – (answers 501 for `/earnings/next`) | report date and SEC filing time, actual EPS, **no estimates** | `1d`/`1w` of any range, last price, company profile | pay per request, USD 0.02 (default budget 1,000 per month = USD 20) |

Earnings are two roles, each with its own default in **Admin → Settings**: **Default Earnings Upcoming Provider** (`earnings_upcoming`: `alphavantage`, `earningsapi`) and **Default Earnings History Provider** (`earnings_history`: all three). `/earnings/next` and `kind=upcoming` use the upcoming default, `kind=reported` the history default and `kind=all` both: unreported events come from the upcoming provider, reported ones from the history provider, an announced event is dropped when the history provider has a reported event of the same symbol within 7 days, and `meta.providers` names both (`meta.provider` is omitted). With one provider for both roles nothing is composed. `provider=` serves every role that provider implements; asking a history-only provider for upcoming events answers 501 with `details.supported` listing the providers of that role. The former single setting `default_earnings_provider` is migrated once to both roles and still accepted as shorthand. Without a configured provider the endpoints answer 503 `No earnings provider configured — enable a provider in the admin UI`.

## Endpoints

| Endpoint | Result |
|---|---|
| `GET /earnings/next?symbols=AAPL,MSFT,SPY` | One row per symbol, in request order: `event` (earliest on or after today in New York, or `null`), `days_until`, `last_reported`, `status` (`ok`, `none_scheduled`, `not_applicable`). Answered from the calendar only: at most one provider request and **never** a history request. |
| `GET /earnings/calendar?symbols=…&from=…&to=…&kind=all` | Events of up to 50 symbols, oldest first. Defaults: `from` = today − 30 days, `to` = today + 90 days, at most 800 days. `format=csv` adds `X-MDH-Data-As-Of`. |
| `GET /companies/{symbol}/earnings?from=…&to=…` | Past and upcoming events of one stock. Defaults: today − 1095 days … today + 400 days. ETF → 422 `CAPABILITY_NOT_SUPPORTED`, unknown symbol → 404. |

`kind` is `all` (default), `upcoming` (announced, `reported: false`; no history is requested from calendar providers) or `reported` (`reported: true`; no calendar or day calendar is requested); another value answers 422.

MCP tools: `get_earnings_calendar` (`symbols`, `from_date`, `to_date`, `kind`, `provider`) and `get_next_earnings` (`symbols`, `provider`); they use the same service, store and cache policy.

```bash
curl 'http://localhost:8000/earnings/next?symbols=AAPL,MSFT,SPY'
curl 'http://localhost:8000/earnings/calendar?symbols=AAPL,JPM&from=2026-11-17&to=2027-02-28'
curl 'http://localhost:8000/companies/AAPL/earnings?provider=alphavantage'
```

### Event fields

`symbol`, `report_date`, `report_time` (`bmo` before the open, `amc` after the close, `during`, `unknown`), `date_status` (`confirmed`, `projected`, `unknown`), `reported`, `fiscal_period_end`, `eps_estimate`, `eps_actual`, `eps_surprise`, `eps_surprise_pct`, `revenue_estimate`, `revenue_actual` (decimal strings; revenue only from `earningsapi`, otherwise `null`), `currency`, `provider`, `updated_at`.

- **Announced dates only.** The Alpha Vantage calendar lists companies that have announced a date. A company that has not (typically a late-January reporter in mid-November) has **no event**: `/earnings/next` answers `none_scheduled` together with `last_reported`. MDH never estimates or extrapolates a date.
- `date_status` is exactly what the provider states. Alpha Vantage does not say whether a date is confirmed, so upcoming events are `unknown`; reported events are `confirmed`. Whether to show an unconfirmed date is the client's decision.
- ETFs (explicit `sec_type=etf` or a well-known ETF ticker) are `not_applicable` without a provider call; index, future and option symbols (`I:SPX`, `F:ES`, `O:…`) are rejected with 422. Share classes keep the canonical dot notation (`BRK.B`); the provider call translates it (`BRK-B`). Preferred shares (`JPM-PD`) are dropped.

### Response metadata

Every response carries `meta.provider`, `meta.data_as_of` (age of the oldest involved data), `meta.stale` and, for the batch endpoints, `meta.symbols[]` with `status` (`ok`, `not_applicable`, `not_found`, `error`), `history` (`complete`, `pending`, `not_requested`) and `message`.

`meta.stale = true` means stored events were served because the provider failed or its request budget is exhausted. Stale responses are never cached. `history: pending` means the provider budget ran out before this symbol's history could be fetched; its upcoming events are still returned (HTTP 200).

## How data is refreshed

There is no background scheduler; requests drive the refresh (`EARNINGS_*` settings, see below).

- **Calendar:** one market-wide request per `EARNINGS_CALENDAR_RESYNC_HOURS` (24 h) for **all** symbols; it always covers the next 365 days, so a later request for any other symbol is served without a provider call.
- **History of a symbol:** fetched when the symbol has none and a request needs dates before today, and again when a stored event of the last `EARNINGS_ACTUALS_WINDOW_DAYS` (10) still has no actual EPS and the history is older than 12 h. After a failed synchronisation the same scope is not retried for `EARNINGS_RETRY_MINUTES` (30).
- **Budget:** the calendar request has priority; due history is fetched in request order until the budget is used up.
- **With the history store** (`DATABASE_URL`): events are stored per provider and survive restarts; a moved report date replaces its old row; an upcoming row and a reported row of the same fiscal period become one event once the actual EPS is known. Database errors fail open (the request is answered as if the store were disabled).
- **Without the store:** the parsed calendar is kept in Redis for `EARNINGS_CALENDAR_RESYNC_HOURS` and per-symbol history goes through the response cache; without Redis every request calls the provider within its budget. `meta.stale` is then never set.

Cost with 100 watched symbols on the free tier: one calendar request per day, about 100 history requests once (spread over four days at 25 per day), then about one per symbol and quarter.

## Request budgets

Metered providers (Alpha Vantage, Financial Datasets) have connection settings `request_budget_per_day` and `request_budget_per_month` (whole numbers, `0` = no limit; editable in **Admin → Providers → provider → Configuration**). Alpha Vantage defaults to 25 per day, Financial Datasets to 1,000 per month.

- One budget covers every capability of the provider, e.g. prices **and** earnings.
- Before each upstream request a counter for the day (`America/New_York`) and the month (UTC) is incremented atomically in Redis, so it holds across replicas. Without Redis a process-local counter is used and the usage display says *this replica only*.
- A request that would exceed a budget is refused **before it is sent**: HTTP 429 `PROVIDER_QUOTA_EXHAUSTED` (`details.provider`, `period`, `budget`). It is logged once at 80 % per period.
- `GET /api/admin/providers/{name}/usage` (admin auth) and the provider details show used/budget, reset time and whether the counters are shared. The Prometheus counter `mdh_provider_upstream_requests_total{provider}` counts requests actually sent.
- Alpha Vantage answers HTTP 200 with a notice instead of an error. A **per-second burst** notice (it also mentions the daily limit and premium plans) is retried with pacing and **never** exhausts the day; only an explicit daily-quota notice sets the day counter to its budget. A *premium endpoint* notice is `PROVIDER_NOT_ENTITLED`, an invalid key `PROVIDER_NOT_AVAILABLE`.

## Alpha Vantage notes

- Free-tier terms apply (personal use, about 25 requests per day); see [alphavantage.co/support](https://www.alphavantage.co/support/#api-key). Realtime and 15-minute delayed data are premium-only.
- Premium-only (answered as `PROVIDER_NOT_ENTITLED`): `outputsize=full`, `TIME_SERIES_DAILY_ADJUSTED`, intraday, `OVERVIEW`. Consequences: daily bars cover only the latest 100 trading days (a longer range returns what exists; with the history store the stored series grows), and intraday intervals are rejected without a provider call.
- **Bars are not adjusted** for splits or dividends (weekly AAPL closes jump from about 499 to about 121 across August 2020). The admin provider details show `price_adjustment: none`; MDH does not adjust. Use an adjusting provider for long-range returns.
- The last price is the **end-of-day** quote; its timestamp is the close (16:00 New York) of the latest trading day.
- Prices and earnings share one daily budget, so Alpha Vantage is meant as an explicitly requested or fallback price provider rather than the default.

## Financial Datasets notes

- Implemented against a pinned copy of the published OpenAPI document (`tests/fixtures/financialdatasets/openapi.json`); the contract tests validate every fixture and every request the provider builds against it. Updating the pinned copy makes schema changes visible (for example a new `filing_window` value).
- Report time comes from the SEC filing: the earliest 8-K of a fiscal period, otherwise the earliest filing; `PRE_MARKET` → `bmo`, `DURING_MARKET` → `during`, `AFTER_HOURS` → `amc` (from 16:00 ET) or `bmo` (before 04:00 ET), `WEEKEND` → `unknown`.
- HTTP 401/402 (no key or used-up credit) are `PROVIDER_NOT_AVAILABLE`; company search is not offered (501). Whether its bars are adjusted is not stated by the schema (`price_adjustment: unknown`).
- x402 per-call payment is not used.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `EARNINGS_CALENDAR_RESYNC_HOURS` | `24` | Age after which the market-wide calendar is requested again |
| `EARNINGS_ACTUALS_WINDOW_DAYS` | `10` | A stored event this recent without actual EPS makes the history due again |
| `EARNINGS_RETRY_MINUTES` | `30` | Pause before a failed synchronisation is retried |
| `CACHE_TTL_EARNINGS_SECONDS` | `21600` | Response cache of the three endpoints and tools (6 h, no market-closed extension; runtime-configurable, `0` disables) |

The cache keys contain the sorted symbols and the New York date, so `?symbols=MSFT,AAPL` and `?symbols=AAPL,MSFT` share one entry (the answer keeps the request order). The Admin cache scope **Earnings** clears all earnings keys, including the provider calendar kept in Redis.

## Not covered

An IBKR implementation (requires a Wall Street Horizon subscription; the capability allows adding it later), fundamentals, analyst estimates and dividends, estimated dates for companies that have not announced, ETFs/indices/futures, non-US listings, a background scheduler, and the history of report-date changes.


## EarningsAPI (per-symbol provider)

`earningsapi` (`https://api.earningsapi.com`, key as query parameter `apikey`) has no market-wide range calendar, so MDH uses two request types and its own store (`upcoming_mode: symbol` with a day calendar):

- **Day-calendar window.** `/v2/calendar/earnings?date=` returns all companies of one day (`pre`, `after`, `notSupplied`). MDH keeps the previous weekday through `EARNINGS_DAY_CALENDAR_WEEKDAYS` (default 7) weekdays ahead synchronised, one request per day. A day is refreshed when its last synchronisation is older than 20 hours and it is the previous weekday, today or one of the next two weekdays (steady state about five requests per weekday, about 110 per month, independent of the watchlist). The previous day's refresh delivers the actual EPS of the reports of that day. A day calendar is authoritative for its date: a moved report date replaces the stale event in the store.
- **Per-symbol requests.** `/v2/earnings?symbol=` returns the upcoming and the reported quarters of one stock. MDH requests a stock only when the store cannot answer: it was never synchronised and the request needs its history (or its next event, which the window does not hold); it has no upcoming event and has reported since its last synchronisation (next quarter, once per quarter) or its last synchronisation is older than `EARNINGS_SYMBOL_RESYNC_DAYS` (default 7; EarningsAPI lists the next quarter only after the company announced it); or a day calendar removed its event. A stock with a known next date is never re-requested for its age. Stocks beyond the remaining request budget are served from the store or answered `status: "error"` with `provider request budget exhausted`, in request order.
- Recorded behaviour (free key, 2026-11-19): invalid key → HTTP 403 `Invalid API Key`; unknown symbol and ETFs → HTTP 404 `{"error":"Symbol not found"}` (404 also counts against the quota); `BRK.B` and `BRK-B` both work and are returned as `BRK.B`; the day calendar is populated about two weeks ahead; quota headers `X-Daily-*` (resets 00:00 UTC) and `X-Quota-*` (monthly) are sent with every response.
- Without the history store the parsed day calendars (7 days) and symbol results (`EARNINGS_SYMBOL_RESYNC_DAYS`) are kept in Redis with the same rules; moved dates are then caught by the day window only.
- Event mapping: `time-pre-market`/`time-after-hours`/`null` → `bmo`/`amc`/`unknown`; `eps_surprise` and `eps_surprise_pct` are computed from estimate and actual; there is no fiscal period end and no confirmation flag (`date_status` is `unknown` until reported); currency is USD.
