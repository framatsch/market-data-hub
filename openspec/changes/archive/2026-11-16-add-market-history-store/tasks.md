## 1. Setup

- [x] 1.1 Add `sqlalchemy[asyncio]`, `asyncpg` and `alembic` via `uv add`; confirm the pinned `httpx==0.26.0` still resolves
- [x] 1.2 Add `DATABASE_URL` (optional; empty string counts as unset), `HISTORY_STORE_RESYNC_SECONDS` (300), `HISTORY_STORE_OVERLAP_BARS` (5, 2–30) and `HISTORY_STORE_MIGRATE_ON_STARTUP` (true) to `app/config.py` with validation; unit tests in `tests/unit/test_config.py`
- [x] 1.3 Document the settings in `.env.example`
- [x] 1.4 Add `history_store_intervals` (list out of `1h`, `4h`, `1d`, `1w`; default `["1d"]`) to `ProviderRuntimeConfig` and `app/admin/provider_config_repository.py` (new column with the default for existing rows); validate it in the admin provider configuration endpoint (422 for other values); tests for default, update, empty list and invalid value

## 2. Schema and engine (`app/store/`)

- [x] 2.1 `app/store/engine.py`: async engine and session factory from `DATABASE_URL`, redacted URL helper, `setup_store()` / `shutdown_store()` returning `disabled` | `connected` | `unavailable`
- [x] 2.2 `app/store/models.py`: `history_series`, `price_bars`, `iv_points_daily` as in design D2 (NUMERIC values, primary keys on `series_id` + `bar_start` / `point_date`, unique series identity including `interval` and `extended_hours`)
- [x] 2.3 Alembic environment and first migration; `run_migrations()` under a PostgreSQL advisory lock, gated by `HISTORY_STORE_MIGRATE_ON_STARTUP`
- [x] 2.4 Call `setup_store()` / `shutdown_store()` in the FastAPI lifespan in `app/main.py`; show the state in the startup banner
- [x] 2.5 Fail-open guard around all store calls: one warning, 30 s cooldown, recovery message; unit tests with a failing session

## 3. Test harness

- [x] 3.1 Integration fixture with a disposable PostgreSQL (Compose file under `tests/compose/`), skipped when no database is available; hermetic unit tests run without `DATABASE_URL` (store disabled)
- [x] 3.2 Fake price and volatility providers that record requested ranges and can return adjusted series, missing days and errors

## 4. Closed-day rule and repositories

- [x] 4.1 `last_closed_day(now)`, `is_closed(day, now)`, `is_bar_closed(interval, bar_start, now, extended_hours)` and `trading_date(bar_start)` (UTC calendar date of a bar start) in `app/market_hours.py`, with tests for session, settle grace, evening and weekend, for the running week and the running hour, and for daily stamps at New York midnight and at UTC midnight
- [x] 4.2 Series repository: get-or-create by identity, coverage update, attempt bookkeeping (`synced_at`, `sync_failed_at`)
- [x] 4.3 Bar and IV point repositories: range read (by `bar_date` for `1d` and `1w`, by `bar_start` for `1h` and `4h`), `INSERT … ON CONFLICT DO UPDATE`, replace-all in one transaction under a transaction advisory lock
- [x] 4.4 Status and delete queries for the admin endpoints (counts per dataset and per price interval, oldest/newest date, delete by dataset, canonical symbol, provider and interval)

## 5. Synchronisation (`app/store/sync.py`)

- [x] 5.1 Planner: from interval, request range, coverage, last attempt and `now` decide `store` | `tail_sync` | `backfill` | `full_load`; pure function with table-driven tests per interval (`1w` start moved to Monday, RTH intraday series settled after the close, intraday `covered_from` at the oldest returned bar)
- [x] 5.2 Overlap comparison over the `HISTORY_STORE_OVERLAP_BARS` newest stored bars: newest-bar overwrite, older-bar difference → reload, volume-only → update; tests for split (daily, weekly and hourly series), late correction and final volume
- [x] 5.3 Per-series in-process lock so concurrent requests share one provider call; test with ten parallel requests
- [x] 5.4 Reload that leaves stored rows unchanged when the provider fails halfway
- [x] 5.5 `Cache-Control: no-cache` ignores the resync interval (read the request through the existing cache request context)

## 6. Price history

- [x] 6.1 `PriceService.get_historical_prices`: route through the store when it is enabled and the interval is in the effective provider's `history_store_intervals`; series identity with interval and (for `1h`, `4h`) `extended_hours`; select `1d` and `1w` by date and `1h`, `4h` by start instant; rebuild `PriceBar` from rows and append the forming bar from the tail
- [x] 6.2 Leave every interval that is not listed for the provider and the disabled or unavailable store on the current code path; a provider error for a listed interval the provider does not deliver is returned unchanged and nothing is stored
- [x] 6.3 Provider failure with covered range → stored bars and a stale marker; uncovered range, `PROVIDER_NOT_ENTITLED` and 501 → error as today
- [x] 6.4 Bars of another provider (`1d` only): own series first, otherwise the covering series with the newest `synced_at`, unmixed, with `meta.source_provider`; nothing written to the requested provider's series
- [x] 6.5 Integration tests for "Stored bars of another provider" and for all scenarios of "Stored intervals per provider", "Price history from the store", "Only closed bars are stored", "Coverage tracking" and "Throttled tail synchronisation"

## 7. Implied volatility

- [x] 7.1 `VolatilityService.get_implied_volatility_history` through the store (tenor and `ric` in the series identity, points without any value not stored, `covered_to` = newest point date)
- [x] 7.2 `VolatilityService.get_implied_volatility_stats` from stored points with the existing `_iv_statistics`; result parity test against the provider-only path
- [x] 7.3 Provider failure with at least 20 stored points of the same provider → stats from the store with the stale marker; fewer → provider error; test that another provider's IV series is never used
- [x] 7.4 Integration tests for the IV scenarios, including "IV point not yet published"

## 8. Response metadata

- [x] 8.1 Typed `meta` model (`data_as_of`, `stale`, `stale_reason`, `source_provider`) for `ResponseEnvelope`; services return the fetch time alongside the data
- [x] 8.2 Set `meta.data_as_of` in the chain, price-history and three volatility routes; `X-MDH-Data-As-Of` on their CSV responses
- [x] 8.3 Tests: value unchanged on `X-FastAPI-Cache: HIT`, new value after `no-cache`, `synced_at` for store-served history
- [x] 8.4 Regenerate/update the OpenAPI description and `skills` references that document the envelope

## 9. Response cache changes (`app/cache.py`)

- [x] 9.1 Key builder: reduce `start` / `end` to the UTC date for daily-or-longer `prices:history`; same rule in `_compose_key` for MCP; tests for moving start time, next day and intraday
- [x] 9.2 Skip the cache write and send `Cache-Control: no-store` for responses marked stale; test that the next request reaches the provider

## 10. Admin API and UI

- [x] 10.1 `GET /api/admin/history-store` and `POST /api/admin/history-store/clear` in `app/api/routes_admin.py` (auth, 422 without `confirm`, 503 when disabled or unavailable, audit log entry); tests in `tests/unit/test_admin_history_store_routes.py`
- [x] 10.2 Admin UI: `HistoryStoreCard` on the Settings page with status, counts (prices also per interval) and the clear dialog with acknowledgement and optional interval; types in `admin/src/types.ts`; (no admin test runner in the repo; type-checked, linted and built)
- [x] 10.3 Admin UI provider details: selection of the stored intervals (`1h`, `4h`, `1d`, `1w`) with the note that an interval the provider does not deliver is not stored; disabled with a hint when the store is disabled; (no admin test runner in the repo; type-checked, linted and built)

## 11. Metrics

- [x] 11.1 Counter `mdh_history_store_reads_total{dataset,result}` incremented once per served request; tests for `store`, `reload`, `stale`, `fallback_provider` and `bypass`

## 12. Deployment and documentation

- [x] 12.1 `docker-compose.yml`: `postgres` service in profile `postgres` (named volume, healthcheck, no host port), `DATABASE_URL: ${DATABASE_URL:-}` and `depends_on` with `required: false` for `market-data-hub`; same for `docker-compose.release.yml.template`; verify the start with and without the profile
- [x] 12.2 `doc/deployment.md`: `DATABASE_URL` is optional, Compose profile, database for Kubernetes (5 Gi volume recommended, 10 Gi with hourly bars), the provider setting `history_store_intervals`, migration switch, rollback by unsetting `DATABASE_URL`
- [x] 12.3 `CHANGELOG.md`: optional store behind `DATABASE_URL`, stored intervals per provider, bars of another provider on failure, `meta.data_as_of`, `meta.stale`, date-based selection of the first and last daily bar
- [x] 12.4 Update `skills/` MDH API reference used by client projects

## 13. Verification

- [x] 13.1 `uv run ruff check app/`, `python skills/lint_check.py --all`, `uv run pytest --maxfail=1 --disable-warnings`
- [x] 13.2 Compose run against real PostgreSQL and Redis with fake providers: first load, repeat without provider call, restart keeps data, database stopped → still serving (run on 2026-11-16 against disposable PostgreSQL and Redis with the real IBKR, LSEG and Polygon providers: first load, repeat from the store, restart keeps data, cache hits and `no-cache`, stale responses bypass Redis; database outage covered by `test_database_failure_is_fail_open`)
- [x] 13.3 Live check with one symbol per provider: compare a store-built daily history and IV stats with the provider-only result (store disabled) for identical values (AAPL on IBKR, LSEG and Polygon: identical bars; IBKR IV stats and history identical; LSEG IV after fixing the missing market field)
- [x] 13.4 Live check of the other intervals per provider before switching them on: stamp of weekly bars (Monday or Sunday), behaviour of long `1h` ranges (lookback, truncation), store-built `1h`, `4h` and `1w` history equal to the provider-only result (IBKR and LSEG `1d`, `1w`, `1h`, `4h` identical; Polygon `1d` and `1w` identical, weekly bars stamped Monday; found and fixed naive timestamps stored in the system time zone)
- [ ] 13.5 Live check of Schwab (daily history and `4h`/`1h`) and of Polygon `4h` (rate limited on the free tier during the run)
