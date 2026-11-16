## Context

MDH answers market data requests from provider APIs and caches whole responses in Redis (`app/cache.py`, capability `response-caching`). The cache is keyed by route, symbol and query string and has market-aware lifetimes: 300 s for a range with a forming bar during the session, until the next open while the market is settled, 900 s for volatility.

This works for data that changes during the day, but not for history:

- A daily bar or IV point of a closed day is immutable, and so is a closed hourly, four-hour or weekly bar, but when its cache entry expires the whole range is downloaded again.
- Different ranges of the same series are different keys and share nothing.
- IV Rank needs about 380 calendar days of IV history per request; with IBKR as volatility provider each cache miss is a gateway round trip, and a gateway outage is an outage of IV Rank.
- Persistent state today is SQLite (`keys.db`: credentials, provider configuration, system settings) on a pod volume.

Measured in production (pod log, 14–16 November 2026): 39 successful daily-history requests, median 696 ms, maximum 1850 ms, none below 60 ms; three 503 from the Schwab rate limiter within one burst of parallel requests; IV stats 1753 ms on success and 12023 ms until a 503.

## Goals / Non-Goals

**Goals:**
- Closed price bars of the stored intervals (`1h`, `4h`, `1d`, `1w`) and IV points are loaded from a provider once and kept.
- An administrator chooses per provider which of these intervals are stored.
- A history or IV request on a stored series needs at most one small provider call (the tail), and none while the market is settled and the series is up to date.
- IV Rank does not depend on provider availability at request time.
- Clients can see the age of the data in every market data response.
- MDH still runs without PostgreSQL (local Docker Compose with SQLite and Redis), and a database outage degrades to today's behaviour.
- One switch, `DATABASE_URL`, decides whether a deployment uses PostgreSQL; a later change can put credentials and settings behind the same switch.

**Non-Goals:**
- Intervals below `1h` and monthly or longer bars. Short intervals are many rows for little reuse; they stay in the Redis response cache.
- Computing an interval a provider does not deliver. The store keeps what the price service returns for an interval; deriving `4h` or `1w` from smaller bars is `add-derived-price-intervals`.
- Storing option chains, quotes or greeks. They change during the session; Redis stays their cache.
- A scheduler that synchronises series in the background or pre-loads a symbol universe. Synchronisation is driven by requests.
- Moving credentials, provider configuration and system settings from SQLite to PostgreSQL. This follows as its own change once PostgreSQL is part of the deployment.
- TimescaleDB (see D11).
- Changing MCP tool result shapes.

## Decisions

### D1: PostgreSQL with SQLAlchemy 2 async, asyncpg and Alembic

The same stack as VisioTrade and TradeSensei, so migrations, test fixtures and operations follow one pattern. `DATABASE_URL` is optional: unset or empty means the store is disabled and no database code runs. This keeps the local setup free of PostgreSQL and makes the disabled mode the same code path as the fail-open path of D10. A database that is configured but unreachable does not stop the start (D10). Migrations run at startup under a PostgreSQL advisory lock (`HISTORY_STORE_MIGRATE_ON_STARTUP`, default `true`), so two replicas starting together migrate once.

*Alternatives:* SQLite next to `keys.db` (no second replica possible, file on a pod volume, weak concurrent writes); keeping history in Redis with a long TTL (it is an LRU cache with a memory cap, entries are whole responses, no partial reads).

### D2: One `series` table plus two narrow fact tables

- `history_series`: `id`, `dataset` (`prices` | `iv`), `symbol` (canonical), `provider`, `interval` (`1h` | `4h` | `1d` | `1w` for prices, `1d` for IV), `extended_hours` (price series of `1h` and `4h` only, otherwise false), `tenor_days` (IV only), `instrument` (IV `ric` override, empty string when none), `sec_type`, `source_instrument`, `covered_from`, `covered_to` (TIMESTAMPTZ; midnight UTC of the date for `1d`, `1w` and IV), `synced_at`, `sync_failed_at`. Unique on (`dataset`, `symbol`, `provider`, `interval`, `extended_hours`, `tenor_days`, `instrument`).
- `price_bars`: `series_id`, `bar_start`, `bar_date`, `bar_end`, `open`, `high`, `low`, `close` (NUMERIC), `volume` (BIGINT). Primary key (`series_id`, `bar_start`).
- `iv_points_daily`: `series_id`, `point_date`, `iv_call`, `iv_put`, `iv` (NUMERIC, nullable as in `VolatilityPoint`). Primary key (`series_id`, `point_date`).

`bar_date` is the UTC calendar date of the provider's bar start. For a daily bar this is its trading date: Polygon stamps a daily bar at midnight New York time (04:00 or 05:00 UTC), the other providers at midnight UTC, so the UTC date is the trading date in both conventions, while the New York date of a UTC-midnight stamp would be the day before. The rule lives in one helper, `trading_date(bar_start)` in `app/market_hours.py`, which `add-derived-price-intervals` reuses to group daily bars into weeks. `1d` and `1w` bars are selected by `bar_date`, `1h` and `4h` bars by `bar_start`. `bar_start` and `bar_end` keep the provider's instants so the response is rebuilt unchanged.

One table holds all intervals; the interval is part of the series, not of the row. `extended_hours` is part of the identity of intraday series because the bars differ: an RTH `4h` bar and an extended-hours `4h` bar of the same period have different values. Values are `Decimal` end to end, as everywhere in MDH.

Providers are never mixed: a series belongs to one provider, exactly like a response-cache key.

### D3: Only closed bars are stored

A day is closed when it lies before the current session date in New York, or is the current session date and `market_state()` is `settled` (close plus 30 minutes grace). This reuses `app/market_hours.py`, including its deliberate simplification that exchange holidays count as weekdays: on a holiday the provider returns no bar, nothing is stored, and the day is recorded as covered.

From this follows when a bar is closed:

- `1d` bar and IV point: its trading date is a closed day.
- `1w` bar: the Friday of its ISO week is a closed day.
- `1h` and `4h` bar: the clock-aligned period that contains its start has ended. Periods are counted from midnight in `America/New_York`, as `current_period_start` in `app/market_hours.py` already does for the cache lifetimes. Without extended hours no period counts as open while the market is settled, so an RTH series is complete after the close and causes no provider calls in the evening.

The forming bar is never stored. It comes from the provider with each tail synchronisation and is held only by the Redis response cache (open-bar lifetime, default 300 s).

### D4: Coverage, not row presence, decides what is missing

Missing rows are ambiguous (holiday, halt, or never loaded), so each series records the range it knows:

- `covered_from`: earliest date (for `1h` and `4h`: instant) ever requested and loaded.
- `covered_to`: newest date or instant known. For prices this is the newest closed bar period at the time of a successful synchronisation. For IV it is the date of the newest point the provider returned, because IV for a day is published some time after the close and "no point yet" must not be recorded as "no point".
- `synced_at`: time of the last successful provider call for the series.

A request for `[start, end]` is served as follows:

1. No series: load `[start, end]` from the provider, store the closed bars, answer.
2. `start` before `covered_from`: load `[start, covered_from + overlap]`, store, extend `covered_from`.
3. Tail is **due** when `covered_to` is before the newest closed bar period, or the request includes the forming bar, and the last attempt (success or failure) is older than `HISTORY_STORE_RESYNC_SECONDS` (default 300): load `[covered_to − overlap, now]`, store the closed bars, keep the forming bar for this response.
4. Otherwise: answer from the store without a provider call.

Providers limit how far back intraday bars reach (Schwab by lookback, LSEG and Polygon by bar count). For `1h` and `4h` series `covered_from` is therefore the start of the oldest bar the provider returned, not the requested `start`: a range the provider did not deliver is not recorded as "no data". A later request for an earlier `start` asks the provider again, throttled by the resync interval like the tail. Stored bars stay when they fall out of the provider's lookback, so an intraday series grows longer than the provider's own history.

For `1w` the requested `start` is moved back to the Monday of its UTC calendar week before planning, so the week that contains `start` is part of the answer whatever weekday `start` is.

In front of this sits the unchanged Redis response cache, so during the session a series is synchronised at most once per open-bar lifetime, and while the market is settled not at all once it is covered through the last closed day.

### D5: Revision detection by overlap

Providers return split-adjusted (some also dividend-adjusted) history, so an adjustment changes every earlier bar. Each tail synchronisation re-reads the `HISTORY_STORE_OVERLAP_BARS` (default 5, at least 2) newest stored bars and compares open, high, low and close exactly:

- Difference only in the newest stored bar: overwrite that row (late corrections of the last session, final volume).
- Difference in any older overlapped bar: the series was revised. Reload `[covered_from, now]` from the provider and replace all rows of the series in one transaction.

Volume alone never triggers a reload. For IV the same comparison applies to `iv_call`, `iv_put` and `iv`.

The overlap is counted in bars, not days, so it means the same for every interval: five weekly bars, five daily bars, five hourly bars. With fewer than two bars a revision could never be told from a correction of the newest bar, hence the minimum of 2. A reload replaces all rows of the series with what the provider delivers now. For an intraday series this drops stored bars older than the provider's lookback: after a revision they would carry unadjusted prices next to adjusted ones.

*Alternative:* a periodic full refresh of every series. It costs the downloads this change removes and detects a split later than the overlap does. The admin clear endpoint remains as the manual tool.

### D6: IV statistics from stored points

`get_implied_volatility_stats` ensures coverage for its window (same start formula as today: `window × 365 / 252 + 14` calendar days), runs the tail rule of D4, then computes `current`, `min`, `max`, IV Rank and IV Percentile from stored points with the existing `_iv_statistics`. The result is identical to today's for identical points. `window_end` already tells a client which day `current` is from; VisioTrade marks a rank as stale when `window_end` is older than 7 days.

### D7: Stale serving instead of an error

When a provider call fails (connection error, timeout, rate limit, paused provider) and the store covers the closed bars of the requested range, MDH answers `200` with the stored data, `meta.stale = true` and `meta.stale_reason` (the error code). The forming bar is absent in that case. `sync_failed_at` is recorded and no new attempt is made for `HISTORY_STORE_RESYNC_SECONDS`, so a dead IB Gateway costs one timeout per interval, not one per request.

Stale responses are not written to the response cache (the backend's `set` is skipped through the existing request-scope mechanism), so recovery of the provider is visible on the next request.

If the store cannot cover the range, the provider error is returned as today. Entitlement and capability errors (403, 501) are never replaced by stored data.

**Bars of another provider.** Series stay separate per provider (volumes, bar instants and adjustment policy differ, and alternating writers would make the overlap comparison of D5 reload a series again and again). Reading across providers is allowed in exactly one case, and for `1d` only: the requested provider failed, its own series does not cover the closed days of the range, and a daily price series of another provider for the same canonical symbol does. Hourly, four-hour and weekly bars are not substituted, because their boundaries differ between providers. Then that series is returned unmixed: every bar carries its real `provider`, and the response carries `meta.stale = true`, `meta.stale_reason` and `meta.source_provider`. If several providers qualify, the one with the newest `synced_at` is used. This never applies to IV: LSEG publishes an ATM IV index and IBKR a 30-day model value, so a rank over points of another provider would be a different number under the same name.

### D8: `meta.data_as_of`

`ResponseEnvelope.meta` exists and is unused. The routes for option chains, price history and the three volatility endpoints set `meta.data_as_of` (UTC, ISO 8601) to the time the service obtained the data from the provider. Because Redis stores the encoded envelope, a cache hit returns the original value without extra work. For store-served history it is the series' `synced_at`. CSV responses carry `X-MDH-Data-As-Of`; the cache coder already preserves response headers of CSV entries.

*Alternative:* an HTTP `Age` header. The cache library rebuilds JSON hits from the stored body only, and intermediaries may rewrite `Age`.

### D9: Day-granular response-cache keys

For `prices:history` with a daily-or-longer interval, the key builder reduces `start` and `end` to their UTC date (`volatility:history` already takes dates). The price service selects stored daily and weekly bars by date, inclusive on both ends, so equal keys mean equal results. A client that sends `start = now − 620 days` with microseconds (VisioTrade did until its fix of 16 November 2026) then hits the cache.

This changes one edge: a `start` with a time later than the first bar's start instant used to exclude that bar and now includes it.

### D10: Concurrency and failure handling

- One in-process lock per series; concurrent requests for the same series share one synchronisation.
- Writes are `INSERT … ON CONFLICT DO UPDATE`; a full reload takes a transaction-scoped advisory lock on the series id, so replicas cannot interleave a replace.
- Database errors are caught at the store boundary: one warning, a 30 s cooldown, and the request continues with the provider alone. Same model as `FailOpenRedisBackend`. This also covers a database that is unreachable at startup: MDH starts, reports the store as unavailable and connects when the database appears.
- `Cache-Control: no-cache` on a request (the existing client bypass) also ignores the resync interval and forces a tail synchronisation; it does not force a full reload.

### D11: Plain PostgreSQL, TimescaleDB-compatible keys

Expected volume (estimate): 500 symbols × 20 years × 252 days ≈ 2.5 million daily rows per provider; weekly bars add a fifth of that. Hourly bars are about 1,750 rows per symbol and year for regular hours (7 per session) and about 4,000 with extended hours (16 per session); providers deliver a few years at most, so 500 symbols with five years are 4 to 10 million rows per provider. A B-tree primary key on (`series_id`, `bar_start`) serves that in milliseconds. TimescaleDB adds an extension to build, license and upgrade and pays off with hundreds of millions of rows, compression or continuous aggregates, i.e. intraday bars or archived chain snapshots. Both fact tables have the date in the primary key, so they can become hypertables later without a schema redesign.

### D12: Admin and metrics

- `GET /api/admin/history-store`: state (`disabled` | `connected` | `unavailable`), redacted URL, settings, per dataset the number of series and rows, oldest and newest date, newest `synced_at`.
- `POST /api/admin/history-store/clear`: body `dataset` (`all` | `prices` | `iv`), optional `symbol`, optional `provider`, `confirm: true`; audit-logged; returns deleted series and rows. Same confirmation pattern as the cache clear endpoint.
- Admin UI: "History Store" card on the Settings page below the response cache card.
- Counter `mdh_history_store_reads_total{dataset, result}` with `result` in `store`, `tail_sync`, `backfill`, `full_load`, `reload`, `stale`, `fallback_provider`, `bypass`. No symbol label.

### D14: Stored intervals are a provider setting

`history_store_intervals` is a field of the provider configuration (`ProviderRuntimeConfig`, table `provider_config` in SQLite): a list out of `1h`, `4h`, `1d`, `1w`, default `["1d"]`. It is edited in the provider details of the Admin UI through the existing provider configuration endpoint and read on every request, like the other provider settings.

A request uses the store when the store is enabled and the requested interval is in the list of the effective provider. Everything else takes the provider-only path. An empty list switches price storage off for that provider. IV series are not affected.

Per provider, because the use differs: a provider used for charts may store `1h` and `4h`, one used for daily screening only `1d`, and a provider with a tight rate limit profits most.

Removing an interval stops reading and writing its series; the rows stay until an admin clears them (the clear endpoint takes an `interval`). Adding it again continues the old series through the normal tail and overlap rules.

The store does not make an interval available. It keeps the bars `PriceService` returns for the interval, and an error from that call is passed on with nothing stored. Today that means a listed interval must be mapped natively by the provider (Schwab has no `1h`, Polygon no `1w`). `add-derived-price-intervals` then lets `PriceService` answer every canonical interval at every provider, and the derived bars are stored through the same path.

*Alternative:* one global list in the environment. Rejected: it cannot differ per provider and needs a restart.

*Alternative:* store only `1h` and `1d` and compute `4h` and `1w` from the stored rows. Rejected here: it ties the store to the derivation rules of the following change and to bucket boundaries that differ from native bars.

### D13: Outlook — the same switch for credentials and settings

Not part of this change, but the reason the switch is designed this way. `KeyRepository`, `ProviderConfigRepository` and `SettingsRepository` are already separate classes behind `app/admin/runtime.py`. A following change can add PostgreSQL implementations and choose by `DATABASE_URL`: set → PostgreSQL, unset → the SQLite file as today, with a one-time import of an existing `keys.db` into empty PostgreSQL tables. Local Compose stays on SQLite; a Kubernetes deployment with `DATABASE_URL` then has no state on a pod volume.

Running several replicas needs more than that: each replica needs its own IBKR client id (the gateway accepts one connection per id), and the Schwab token refresh must be coordinated. Both belong to that later change.

## Risks / Trade-offs

- **A revision that leaves the five newest bars unchanged is not detected** → A split or dividend adjustment changes all earlier bars, so this needs a provider correcting only old data. The admin clear endpoint reloads a series on demand.
- **Stale data served as if current** → `meta.stale`, `meta.data_as_of` and (for IV) `window_end` are in every such response; stale responses are not cached; clients that ignore `meta` see at worst the closed days they would have seen before the outage.
- **IV points published late** → `covered_to` for IV is the newest point date, so the tail stays due and is retried every resync interval until the point arrives.
- **Holidays** → Not modeled; the tail is asked once per interval on a holiday and returns nothing new. This is the cost of one small provider call, as today.
- **Continuous futures series (`F:ES`)** → Providers restitch them at a roll; the overlap comparison turns that into a reload.
- **Two modes to test (with and without PostgreSQL)** → The disabled mode is the provider-only path that exists today and that the fail-open rule needs anyway; the unit suite runs it without a database, the integration suite runs the store against PostgreSQL.
- **Bars of another provider differ slightly** → Only served when the requested provider failed and has nothing stored, always marked stale with `meta.source_provider`, never cached, never mixed with bars of the requested provider.
- **Truncated intraday answers** → A provider that cuts a long intraday range (LSEG at 1000 bars, Polygon at 5000 aggregates) returns fewer bars than asked. `covered_from` follows the oldest returned bar, so the cut is not stored as a gap at the old end. A cut in the middle of a range would be; the live check covers each provider's behaviour.
- **Weekly bar stamps differ per provider** → Selection uses the UTC date of the bar start from the Monday of the start week. A provider that stamps a week on Sunday would lose the first week of a range. Verified per provider in the live check before `1w` is switched on for it.
- **A stored interval the provider does not deliver** → The setting accepts it, the request fails as today and nothing is stored. The Admin UI states this next to the selection.
- **Slightly different first bar for clients with a time of day in `start`** → Documented in the changelog; daily bars are day-granular by nature.

## Migration Plan

1. Roll out with `DATABASE_URL` unset: only `meta.data_as_of` and the day-granular keys take effect. Existing Redis entries under old keys expire on their own.
2. Provide PostgreSQL (Kubernetes: a database with a 5 Gi volume, 10 Gi when hourly bars are stored, in the `market-data-hub` namespace, like the other applications of the cluster) and set `DATABASE_URL`. Migrations run at startup. The store fills on demand; the first request per series is a full load, as every request is today. Every provider starts with `history_store_intervals` `["1d"]`; further intervals are switched on per provider in the Admin UI.
3. Rollback: unset `DATABASE_URL`. No data migration in either direction; the tables can be dropped.

## Open Questions

- Should the default option-chain lifetime drop from 900 s to 300 s? It is already adjustable in the Admin UI and is independent of this change, so it is left out here.
- Whether a later change adds a background synchronisation for a configured symbol universe, so that even the first request of the day needs no provider call.
