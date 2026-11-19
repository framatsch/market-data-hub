# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- EarningsAPI provider (`earningsapi`, free key): upcoming report dates, reported quarters and
  revenue estimate/actual from `/v2/earnings` (per symbol) and `/v2/calendar/earnings` (day
  calendar). Request pacing for 60 per minute, request budget defaults 100 per day and 1,000
  per month, connection test, key in the encrypted key store.
- Day-calendar window for providers with a day calendar (`EARNINGS_DAY_CALENDAR_WEEKDAYS`,
  default 7) and per-symbol refresh rules (`EARNINGS_SYMBOL_RESYNC_DAYS`, default 7); moved
  report dates replace stale events in the store (`calendar-day:YYYY-MM-DD` sync scopes).
- `revenue_estimate` and `revenue_actual` on earnings events (JSON, CSV, MCP); Alembic
  migration `0004`.
- `kind` parameter (`all`, `upcoming`, `reported`) for `GET /earnings/calendar`,
  `GET /companies/{symbol}/earnings` and the MCP tool `get_earnings_calendar`.
- `GET /providers`: `available.earnings_upcoming`, `available.earnings_history`,
  `defaults.earnings_upcoming`, `defaults.earnings_history` and `defaults.earnings`;
  composed earnings responses carry `meta.providers`.

### Changed

- Earnings are split into two interfaces and capabilities, `earnings_upcoming`
  (`BaseEarningsUpcomingProvider`) and `earnings_history` (`BaseEarningsHistoryProvider`);
  `earnings` stays in the catalog as their union. The setting `default_earnings_provider` is
  replaced by `default_earnings_upcoming_provider` and `default_earnings_history_provider`
  (migrated once, still accepted as shorthand for both). Admin UI: two default dropdowns and
  `Earnings upcoming` / `Earnings history` chips.
- A history-only provider asked for upcoming events answers 501 with `details.supported`
  naming the providers of that role.

## [1.5.1] - 2026-11-18

### Fixed

- Financial Datasets: daily and weekly bars were shifted back by one day because the live API
  sends bare trading dates (`2026-11-17`) although its schema documents UTC timestamps. Bare
  dates are now taken as the trading day.
- Financial Datasets: later 8-K filings repeat prior-year periods as comparatives and were
  reported as the earnings release of that period. Filings more than 120 days after the period
  end are ignored, so earnings keep their real report date.
- Financial Datasets: EPS derived as annual minus quarters arrived unrounded
  (e.g. `0.9712633647579039`); it is now rounded to cents.
- Admin UI: stored history intervals are labelled `native`, `derived` or `not available`.
  Before, every interval that was not native was shown as `derived`, even when the provider
  has no smaller bars to aggregate it from (e.g. `1h`/`4h` for Financial Datasets).

### Changed

- Dockerfile: the Admin UI is built with Node 22 (was Node 20).

## [1.5.0] - 2026-11-17

### Added

- Earnings calendar: new provider capability `earnings` with the endpoints
  `GET /earnings/next`, `GET /earnings/calendar` and `GET /companies/{symbol}/earnings`
  (CSV export) and the MCP tools `get_next_earnings` and `get_earnings_calendar`. Events carry
  report date, release time (`bmo`/`amc`/`during`/`unknown`), the date status as stated by the
  provider, EPS estimate/actual/surprise and provenance (`meta.provider`, `meta.data_as_of`,
  `meta.stale`, per-symbol `meta.symbols`). Only announced dates are delivered; MDH never
  estimates a date. Events are stored in the history store and refreshed on request (one
  market-wide calendar request per 24 h); provider failures serve stored events as stale.
  New settings `EARNINGS_CALENDAR_RESYNC_HOURS`, `EARNINGS_ACTUALS_WINDOW_DAYS`,
  `EARNINGS_RETRY_MINUTES`, `CACHE_TTL_EARNINGS_SECONDS`; new admin cache scope `earnings`,
  system default `default_earnings_provider` and Alembic migration `0003`.
- Providers `alphavantage` (free key: announced calendar, quarterly history, `1d`/`1w` bars of
  the latest 100 trading days, end-of-day quote; bars are **not split-adjusted**) and
  `financialdatasets` (pay per request: filing-based earnings history, prices, company
  profile; implemented against its pinned OpenAPI schema with contract tests). Both are
  disabled by default.
- Request budgets for metered providers: `request_budget_per_day` / `request_budget_per_month`
  shared by all capabilities of a provider, counted atomically in Redis (process-local
  fallback), refusing requests over the budget before they are sent with 429
  `PROVIDER_QUOTA_EXHAUSTED`. `GET /api/admin/providers/{name}/usage`, a usage display in the
  Admin UI and the metric `mdh_provider_upstream_requests_total`.
- Admin UI: Earnings capability chip, Default Earnings Provider, earnings cache TTL, budget
  settings and usage, price adjustment in the provider details. UI tests with Vitest
  (`npm test` in `admin/`).

### Fixed

- Admin provider configuration: the default `Retry Backoff` of `0.5` s made browsers refuse to
  submit the form (step mismatch).
- LSEG resolved US ETF tickers to foreign listings (e.g. `SPY` → `SPYm.BA` in ARS, `QQQ` →
  `QQQ.CD`), so LSEG ETF quotes and history were wrong. Ticker lookup now prefers the US
  primary listing (`SPY`, `QQQ.O`, `GLD`), then the active US main-issue quote (`GOOG.O`), and
  falls back to the previous search. Share classes map to LSEG's spaced ticker
  (`BRK.B` → `BRK B` → `BRKb`). Already stored LSEG ETF series are not reloaded automatically.
- LSEG company profile and search returned hard-coded placeholder data. They now come from
  the LSEG Search API (name, exchange, currency, TRBC sector/industry, employees; stocks and
  ETFs). Website and description stay empty: the account has no DataGrid scope.

## [1.4.0] - 2026-11-16

### Added

- Optional history store (PostgreSQL, enabled by `DATABASE_URL`): closed price bars of
  `1h`, `4h`, `1d`, `1w` (selectable per provider via `history_store_intervals`, default
  `["1d"]`) and daily IV points are loaded once and topped up incrementally with split
  detection. IV Rank/Percentile are computed from stored points. Fail-open on database
  errors; Compose profile `postgres`; admin status/clear endpoints and a History Store card.
- Stored data is served with `meta.stale = true` when a provider fails; daily bars of another
  provider may be served (`meta.source_provider`). Stale responses are never cached.
- `meta.data_as_of` on option chain, price history and volatility responses
  (`X-MDH-Data-As-Of` for CSV), preserved across response-cache hits.
- Canonical price intervals `1m 5m 15m 1h 4h 1d 1w` work against every price provider:
  missing intervals are derived by aggregating smaller bars (`source_interval` on the bar,
  clock-aligned `America/New_York` buckets, ISO weeks, whole-bucket range widening).
  `60m` and `1wk` are aliases. Admin API/UI list native and derived intervals per provider.

### Fixed

- LSEG implied volatility for stocks and ETFs failed with 422 "market does not match the
  security type" because LSEG no longer fills the market field `GN_TXT16_5` on equity ATMIV
  records. A missing market is now accepted when the exact `<SYMBOL>ATMIV.U` record and its
  underlying (`AAPL.O`, `SPY`) match the requested symbol, as already done for indices; futures
  records and an explicitly conflicting market remain errors.
- The benign websocket "close status: 1001" ERROR log that LSEG snapshot requests produce on a normal close is
  suppressed; other close codes are still logged.
- History store: naive bar timestamps (for example IBKR daily bars) were stored in the system
  time zone instead of UTC.

### Changed

- Response-cache keys of daily-or-longer history use the UTC date of `start`/`end` and the
  normalized interval. The first and last daily bar are selected by date, not timestamp.
- **BREAKING**: LSEG `15m` returns real 15-minute bars (derived from `5m`); LSEG `2m` is
  rejected with 422. An unsupported interval returns 422 `DATA_VALIDATION_ERROR`.

## [1.3.2] - 2026-11-14

### Fixed

- IBKR connection handling: concurrent requests no longer open several sockets on one
  client. Previously a race leaked a socket that kept the client id busy at the gateway
  (error 326 `client id already in use`), so every later IBKR request failed with an
  empty error until the pod was restarted. Connects are now serialized, failed attempts
  close their socket, the IB error handler is registered once, the gateway startup sync
  of positions/orders/executions is skipped (connect ~0.1 s instead of ~8 s), and
  connection errors name the cause (e.g. client id conflict, `TimeoutError`).
- `GET /providers` listed a hard-coded `available` set (Schwab missing, LSEG shown for
  options, Finnhub shown for company data). It is now derived from the enabled providers
  and the capabilities they implement.
- Admin UI About dialog showed a stale version (`admin/package.json` was never bumped
  for releases). It now reads the version from `GET /health`, which exposes the new
  `version` field (backend `APP_VERSION`), so it always matches the running image.
- `skills/bump_version.py` also refreshes `uv.lock`, and a unit test verifies that
  `pyproject.toml`, `uv.lock` and the admin package files carry the same version.

## [1.3.1] - 2026-11-14

### Fixed

- IBKR provider now applies the gateway settings saved in the Admin UI (`host`,
  `port`, `client_id`, `market_data_type`). Previously it only read the
  `IBKR_HOST`/`IBKR_PORT` environment defaults (`127.0.0.1:4001`), so "Test
  connection" failed with `Connection refused` for any remote gateway. Changing
  the endpoint now drops an open connection so the next request reconnects to the
  new gateway.

## [1.3.0] - 2026-11-09

### Added

- Namespaced symbols with one grammar across REST, MCP and WebSocket: bare symbols
  are stocks/ETFs, `I:`/`^` are indices, `F:`/`/` futures and `O:` option ids. A
  central parser (`app/utils/symbols.py`) resolves prefix/`sec_type` conflicts and
  responses return canonical symbols.
- Per-provider symbol mapping (IBKR Index/ContFuture, LSEG `.ROOT`/`ROOTc1`,
  Schwab `$ROOT`/`/ROOT`, Polygon `I:ROOT`) with declared support sets; unsupported
  combinations answer 501 `CAPABILITY_NOT_SUPPORTED` before any provider call.
- New 403 `PROVIDER_NOT_ENTITLED` error for runtime subscription/entitlement denials
  (applied after previous-close and delayed-data fallbacks); Admin UI shows provider
  support sets.

### Changed

- **Breaking:** `symbol` in responses is canonical (`I:SPX`, `F:ES`; stocks
  unchanged); missing subscriptions answer 403 instead of 503; `.SPX`/`$SPX` input
  is rejected; index/future requests at providers without a mapping answer 501;
  cache keys changed (old entries expire).

### Fixed

- Stored credentials encrypted with another `APP_ENCRYPTION_KEY` no longer break
  provider configuration or the admin credential list; they are logged and treated
  as unconfigured.
- Schwab futures quotes are keyed by the active contract; LSEG index ATMIV records
  without a market field are handled.

## [1.2.1] - 2026-11-07

### Added

- Production `docker-compose.release.yml` (plus `env.example` and `README.md`) is
  attached to every GitHub release, pinned to the matching image tag; releases
  list their `ghcr.io/framatsch/market-data-hub` image.

### Changed

- Repository and GHCR images moved to the `framatsch` GitHub account
  (`ghcr.io/framatsch/market-data-hub`); Admin UI links updated.
- README consolidated: removed unsupported LSEG sections and verbose internals.

## [1.2.0] - 2026-11-06

### Added

- Underlying implied-volatility snapshots and daily history from LSEG and IBKR,
  plus provider-independent IV Rank/Percentile through three REST endpoints and
  three MCP tools. All underlying IV uses four-place decimal fractions; provider
  support metadata and a DB-backed default expose supported markets and tenors.
  New settings: `IBKR_IV_TIMEOUT_SECONDS` (default `10`, IV tick wait) and
  `CACHE_TTL_VOLATILITY_SECONDS` (default `900`, Redis cache for IV
  snapshots/stats/open history, no market-closed extension).
- Shared, fail-open Redis response caching for option chains and historical prices,
  including JSON/CSV HIT/MISS headers, ETag revalidation, and client bypass headers.
- Extended caching to company profiles, search, news (JSON/CSV), market status,
  and six MCP tools with forced refresh; added capability-aware keys, configurable
  TTLs, market-status transition caps, and matching Admin UI counts/clear scopes.
- Market- and bar-state-aware TTLs with runtime policy overrides, authenticated
  admin status/policy/confirmed scoped clearing APIs, and a Response Cache card
  on the Admin Settings page.
- Compose Redis service with persistent RDB snapshots, bounded LRU memory and
  internal-only networking; hermetic cache tests and isolated Compose verification.
- `schwab_cli.py`: CLI to download Schwab accounts, positions and transactions
  into the wrapped JSON format used by the Trade Sensei importer (with unit tests).

### Changed

- Removed unsupported LSEG news integration from provider capabilities, the
  public provider catalog and REST/MCP guidance. Use Finnhub, IBKR or mock for
  news; an obsolete LSEG news default is treated as unconfigured. Clear old
  `company_news` cache entries for `provider=lseg` when upgrading with Redis.
- Schwab option-chain and option-quote `implied_volatility` now uses a decimal
  fraction (`0.22345` = 22.345%), consistent with IBKR, Polygon and underlying
  IV values. Multiply by 100 for percentage display. Missing/NaN values and
  negative sentinels such as `-999` now return `null`.

### Fixed

- Normalized historical REST/MCP request date ranges to UTC before provider
  calls, fixing IBKR's naive/aware datetime subtraction error when `end` is
  omitted or timezone forms are mixed. Both channels use UTC-aware current-time
  defaults and derive a missing start from the effective end minus 30 days.
- Admin UI TypeScript and React Hooks lint failures: typed API results and errors,
  derived form defaults that preserve local edits, valid sidebar route matching,
  and OAuth polling timer cleanup.
- Resolved the `E402` lint error in `app/logging_config.py` (misplaced
  `typing` import), so `ruff check app/` passes cleanly.

### Documentation

- Updated README, provider/Finnhub/news guides and Copilot instructions for the
  LSEG news removal, underlying IV and response-cache changes; synced and
  archived the OpenSpec changes (`underlying-implied-volatility`,
  `extend-response-cache-coverage`).

## [1.1.3] - 2026-09-03

### Changed
- **Config:** Implemented dynamic versioning for the UI and API. The frontend now reads its version directly from `package.json`, and the Python backend (FastAPI and MCP server) reads it directly from `pyproject.toml` via `tomllib`.
- **Release:** Automated the `bump_version.py` skill to seamlessly handle `git push`, tag pushing, and `gh release create` to trigger Discord notifications automatically.

## [1.1.2] - 2026-09-02

### Fixed
- **Admin UI:** Configured provider credentials rendered as empty input fields instead of masked values. Two changes in 1.1.1 landed four hours apart and were never reconciled: `22aff53` made the frontend read a cleartext `value` field from `GET /api/admin/credentials`, then `2889502` hardened that endpoint back to metadata-only without touching any frontend file. The leftover `cred.value` was always `undefined` and silently collapsed to `''` via `|| ''`. Configured secrets now render as a mask, and the visibility toggle fetches plaintext on demand through the already-existing rate-limited, audit-logged `/api/admin/credentials/{provider}/{credential}/reveal` endpoint — which the frontend had never called. This supersedes the "cleartext backend transmission" approach described in the 1.1.1 notes below; the metadata-only backend posture is retained unchanged.

### Changed
- Consolidated four drifting copies of the credential TypeScript type into a single `CredentialMetadata` in `admin/src/types.ts`, corrected `provider_name` → `provider` to match the actual API response, and removed the phantom `value` field that TypeScript could not catch because `fetcher()` results are unvalidated type assertions. Added `CredentialReveal` for the reveal endpoint.

## [1.1.1] - 2026-08-14

### Fixed
- **API/MCP:** Fix service discovery on Kubernetes by adding `proxy_headers=True` to Uvicorn, ensuring `url_for` generates the correct external URL behind an Ingress.

### Added
- Admin Settings UI and Backend API (including provider test-connection endpoints and capabilities display).
- News service integration.
- **Schwab Provider** implementation (including OAuth flow and options support).
- Discord webhook support for alerts and test connections.
- Support for secure provider credentials storage via `keys.db` (including a generation script).
- Remote MCP connection support (e.g., for Claude integration) and provider overrides.
- **Regular Trading Hours (RTH):** Added `extended_hours` query parameter (default: `false`) for historical prices. Intraday intervals now automatically filter out pre/after-market data for IBKR, Polygon, and LSEG by default.
- Auto-sync background token watcher for Schwab OAuth integration.

### Changed
- **Security:** Moved all provider API keys and credentials (including Finnhub) to the secure `keys.db`, removing them from environment variables.
- Consolidated provider admin UI, integrating Schwab OAuth settings directly into `routes_admin.py`.
- Refactored Admin UI credential masking to use native browser password fields and cleartext backend transmission, removing complex "fetch-on-demand" logic.
- Gated auto-reload functionality strictly behind `APP_ENV=dev` and `RELOAD=true`.
- Refactored LSEG provider (test connections now validate session only).
- Updated CI/CD pipeline to use `devel` branch triggers and Docker GHCR tags.
- Consolidated agent memory instructions and runtime configuration documentation.
- Refactored service-layer provider access to use async context-managed registry usage paths, enabling in-flight tracking and safer provider reload/close behavior.

### Fixed
- Fixed silent fallbacks for unsupported historical data intervals across all providers (LSEG, IBKR, Polygon). Requests for unknown intervals (e.g. `4h`) now correctly fail with a `ProviderError` (HTTP 400).
- Fixed Claude remote MCP connection issues.
- Fixed Prixe provider to correctly send ticker instead of symbol.
- Fixed empty default provider dropdowns and removed custom logo in Admin UI.
- Fixed admin credential handling and log attribution.
- Resolved integration test flakiness by using mock providers for MCP tests.
- Cleaned up unused variables and linting errors across the codebase.
- Hardened admin static asset serving against path traversal and malformed path inputs (including null-byte edge cases).
- Changed admin credentials listing to metadata-only and added guarded credential reveal behavior with explicit validation, per-user rate limiting, and reveal audit context.
- Moved LSEG quote/history/news blocking operations off the event loop via thread offloading and added regression coverage.
- Improved provider registry reload safety with copy-on-write swap, deferred close semantics, and in-flight provider drain tracking.
- Fixed Schwab token persistence/watcher robustness (correct repository import, typed watcher task lifecycle, and logged fallback behavior).
- Fixed strict typing regressions and updated service tests for async context-manager based provider access.


## [1.0.0] - 2026-05-31
### Added
- Integrated **Polygon.io** provider for high-performance US stocks and options data.
- Added **Prixe** provider for real-time stock price lookup.
- Implemented `ENABLED_PROVIDERS` environment variable for selective provider loading.
- New **Startup Protocol** banner in logs for immediate visibility of active features.
- Enabled **CORS** support to allow connection from the web-based MCP Inspector.
- Comprehensive **unit test suite** with 140+ tests and over 70% coverage.
- Detailed **Provider Setup Guide** (`doc/providers-setup.md`).
- Integrated **MCP (Model Context Protocol)** directly into the FastAPI router.

### Changed
- Removed deprecated Schwab provider.
- Refactored `LSEGProvider` to use explicit date ranges for historical data.
- Isolated network-intensive integration tests from default test runs and CI.
- Updated project tools in `tools/` for the Market Data Hub structure.

### Fixed
- Improved resilience of `ProviderRegistry` against missing dependencies.
- Fixed IBKR connection hangs during test teardown.
- Corrected Pydantic model mappings for various data providers.

## [0.1.0] - 2026-05-30
### Added
- Initial project setup with FastAPI and MCP support.
- Integration with IBKR, LSEG, Schwab, and Finnhub providers.
- Basic price, company, and options endpoints.
