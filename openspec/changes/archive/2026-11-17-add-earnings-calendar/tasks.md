## 0. Spikes (before implementation)

- [x] 0.1 Alpha Vantage spike `tmp/alphavantage_spike.py` with the free key (`ALPHAVANTAGE_API_KEY` in `tmp/.env`): calendar `3month`/`12month`, `EARNINGS` for AAPL, BRK-B, BRK.B, SPY, unknown ticker, `TIME_SERIES_DAILY` compact/full, `DAILY_ADJUSTED`, `WEEKLY`, `INTRADAY`, `GLOBAL_QUOTE`, `OVERVIEW`; raw responses in `tmp/alphavantage_spike_out/`
- [x] 0.2 Record `timeOfTheDay`/`reportTime` values, calendar size and coverage (announced dates only), `None` values, share-class and preferred-share notation, free vs. premium functions, split adjustment in `design.md`
- [x] 0.3 Copy the spike responses needed as fixtures to `tests/fixtures/alphavantage/` (trim the calendar to about 30 rows, keep AAPL and BRK-B history, daily, weekly, quote and the premium notice)
- [x] 0.4 Define notice detection from the recorded burst notice: only explicit daily-quota exhaustion exhausts the day; retain the 25/day default and New York budget boundary. User approved deferring live daily-limit/reset verification to task 9.3a.
- [x] 0.5 Financial Datasets without key: add `jsonschema` as a dev dependency (`uv add --dev jsonschema`; the OpenAPI 3.0 component schemas are validated as JSON Schema after resolving `$ref` and `nullable`), pin `https://www.financialdatasets.ai/openapi.json` as `tests/fixtures/financialdatasets/openapi.json`, write schema-conformant fixtures (earnings with 8-K and 10-Q per period and all `filing_window` values, prices day/week with pagination, snapshot, company facts, 401/402/404 bodies) and a contract test that validates fixtures and built requests against the pinned schema
- [x] 0.6 IBKR probe (`tmp/ibkr_earnings_probe.py`, `tmp/ibkr_tick456_probe.py`): WSH and all fundamental reports not allowed for the account, tick 456 dividends available; recorded in `design.md` (no implementation in this change)

## 1. Model, capability and budget

- [x] 1.1 `app/models/earnings.py`: `EarningsEvent`, `NextEarnings`, per-symbol status and `meta.symbols` shape (Decimal fields, enums per design D2)
- [x] 1.2 `BaseEarningsProvider` in `app/providers/base.py` with `get_upcoming_earnings`, `get_earnings_history`, `test_connection`
- [x] 1.3 Registry: `default_earnings_provider` (allowlist, reload, capability check), `use_earnings_provider()`, `earnings` in `list_available_providers`, 503 message "No earnings provider configured — enable a provider in the admin UI"; tests for default resolution, missing capability and fresh install
- [x] 1.4 Error code `PROVIDER_QUOTA_EXHAUSTED` (`app/utils/errors.py`) mapped to HTTP 429 in `app/main.py`; test
- [x] 1.5 `app/providers/request_budget.py`: day/month counters in Redis with expiry, process-local fallback, refusal before sending, 80 % warning once per period, `exhaust_day()` for provider throttle notices, `mdh_provider_upstream_requests_total`; unit tests for reached budget, new day/month, no limit, Redis down
- [x] 1.6 Connection settings `request_budget_per_day` / `request_budget_per_month` in the allowlist and the provider configuration endpoint (422 for negative values); `GET /api/admin/providers/{name}/usage` (admin auth); tests

## 2. Alpha Vantage provider (`app/providers/alphavantage.py`)

- [x] 2.1 Register `alphavantage` in `KNOWN_PROVIDERS`, `CREDENTIAL_ALLOWLIST` (`api_key`), `PROVIDER_CAPABILITIES` (`["prices", "earnings"]`), registry class map, metrics provider set; budget default 25 per day
- [x] 2.2 `httpx.AsyncClient` with timeout/retry/rate limit from the runtime config; detection of `Information`/`Note`/`Error Message` per spec (rate limit, premium, invalid key); `map_httpx_http_error` for non-200; every request through the budget
- [x] 2.3 `get_upcoming_earnings`: horizon selection, CSV parsing, release-time mapping, empty estimate, preferred-share filter, local filtering by roots and range
- [x] 2.4 `get_earnings_history`: JSON mapping of `quarterlyEarnings`, `None` handling, dash notation for share classes, `{}` → `DATA_NOT_FOUND`
- [x] 2.5 Prices: `native_intervals {1d, 1w}`, `price_sec_types`/`price_history_sec_types {stock, etf}`, `TIME_SERIES_DAILY` compact and `TIME_SERIES_WEEKLY` with range filtering and week-bucket mapping, `GLOBAL_QUOTE` with close-of-day timestamp, `price_adjustment: "none"` in the admin provider details
- [x] 2.6 `test_connection()` with one `GLOBAL_QUOTE`
- [x] 2.7 Unit tests with the fixtures: calendar parsing and filtering, history mapping, share classes, daily/weekly mapping and ranges beyond the compact window, quote time, unsupported intraday interval (no provider call), throttle/premium/invalid-key notices, budget refusal without request, prices and earnings sharing one budget

## 2a. Financial Datasets provider (`app/providers/financialdatasets.py`)

- [x] 2a.1 Register `financialdatasets` (`api_key`, capabilities `["prices", "companies", "earnings"]`, budget default 0 per day / 1000 per month), `X-API-KEY` header, 402 → `PROVIDER_NOT_AVAILABLE`, `map_httpx_http_error`, pagination via `next_page_url`
- [x] 2a.2 `earnings_upcoming = False`; `get_earnings_history` from `/earnings` (earliest filing per `report_period`, `filing_window` mapping, actual EPS, no estimates)
- [x] 2a.3 Prices: `/prices` `day`/`week` for the requested range, UTC `time` to New York trading date, `/prices/snapshot` as last price, `price_adjustment: "unknown"`
- [x] 2a.4 `get_company_profile` from `/company/facts`; `search_companies` → 501 `CAPABILITY_NOT_SUPPORTED`
- [x] 2a.5 `GET /earnings/next` with a provider without upcoming support → 501 without provider call (service check)
- [x] 2a.6 Unit tests with the fixtures: earnings mapping (8-K preference, `AFTER_HOURS` before 04:00 and after 16:00, `WEEKEND`), pagination, prices, snapshot, company facts, 401/402/404, budget; contract test green

## 3. Store (`app/store/`)

- [x] 3.1 Models `earnings_sync` and `earnings_events` (design D4) and Alembic migration `0003_earnings`
- [x] 3.2 Repository: read by provider/symbols/range, calendar replace in one transaction, history upsert, removal of calendar rows whose quarter is reported, sync bookkeeping
- [x] 3.3 Integration tests against the disposable PostgreSQL fixture: moved report date, calendar for unrequested symbols, reconciliation of calendar and history rows, provider isolation

## 4. Earnings service (`app/services/earnings_service.py`)

- [x] 4.1 Settings `EARNINGS_CALENDAR_RESYNC_HOURS` (24), `EARNINGS_ACTUALS_WINDOW_DAYS` (10), `EARNINGS_RETRY_MINUTES` (30) in `app/config.py` and `.env.example`
- [x] 4.2 Symbol handling: parse and de-duplicate, 50-symbol limit, ETF → `not_applicable`, index/future/option → 422
- [x] 4.3 Refresh planner as a pure function (design D5: calendar due, history due, retry pause, budget-limited history in request order) with table-driven tests
- [x] 4.4 Synchronisation and reading with the store; stale serving on provider failure or exhausted budget; fail-open on database errors
- [x] 4.5 Mode without store: provider calendar in Redis, history through the response cache
- [x] 4.6 `next` selection and `days_until` in New York time, statuses, reconciliation of upcoming and reported events, `meta.provider`, `meta.data_as_of`, `meta.stale`, `meta.symbols[].history`
- [x] 4.7 Unit tests with a fake earnings provider recording calendar and history calls

## 5. HTTP API and caching

- [x] 5.1 `app/api/routes_earnings.py`: `GET /earnings/calendar` and `GET /earnings/next`; `GET /companies/{symbol}/earnings` in `routes_companies.py` (registered before `/{symbol}`); CSV export with `X-MDH-Data-As-Of`
- [x] 5.2 Cache policy key `cache_ttl_earnings_seconds` (env `CACHE_TTL_EARNINGS_SECONDS`, default 21600), key segments, normalised `symbols`, day-granular dates, request-order restore for `next`, admin scope `earnings` in status and clear
- [x] 5.3 OpenAPI descriptions and examples; route tests for validation errors, statuses, all-failed error, cache hit with reordered symbols, stale responses not cached

## 6. MCP

- [x] 6.1 Tools `get_earnings_calendar` and `get_next_earnings` with schemas, handlers through the service and the earnings cache policy; tests

## 7. Admin UI

- [x] 7.1 `Earnings` capability chip, "Default Earnings Provider" dropdown, earnings TTL in the cache policy form, `earnings` in cache status/clear
- [x] 7.2 Alpha Vantage and Financial Datasets key fields, budget settings, usage display (day/month, reset time, shared flag) and `price_adjustment` in the provider details
- [x] 7.3 UI tests for chip, dropdown, budget settings and usage display

## 8. Documentation and release

- [x] 8.1 `README.md` and `doc/` (provider overview with cost model, endpoints, settings, budget behaviour, free-tier terms, unadjusted Alpha Vantage bars, announced-dates-only calendar), `CHANGELOG.md`
- [x] 8.2 Lint (`uv run ruff check app/`, `python skills/lint_check.py --all`) and the full test suite

## 9. Live verification

- [x] 9.1 With a free key: `GET /earnings/next` for a 25-symbol watchlist including ETFs and BRK.B; confirm one upstream request in the usage endpoint
- [x] 9.2 `GET /companies/AAPL/earnings` and a calendar with a past range; confirm history requests and budget counting; repeat with the store enabled and confirm no upstream request
- [x] 9.3 `GET /prices/AAPL/history?interval=1w&provider=alphavantage` and `interval=1d`; and, once a Financial Datasets key with credit exists, `GET /prices/AAPL/history?interval=1d&provider=financialdatasets` for 620 days across a split, SPY prices and `GET /companies/AAPL/earnings?provider=financialdatasets`; compare report dates and times of both providers for five symbols and set `price_adjustment` from the result
  - Done live 2026-11-17 (Alpha Vantage): `1w` AAPL across the 2020 split (499.23 → 120.96, unadjusted) and `1d` (21 bars of the compact window), `1h` rejected without a provider call, end-of-day last price at 16:00 ET. The Financial Datasets part is not verified live (no key with credit yet); it is covered by the schema contract tests.
