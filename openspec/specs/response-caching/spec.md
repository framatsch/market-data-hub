# response-caching Specification

## Purpose
Define shared, fail-open Redis response caching for option chains and historical
prices, with provider-isolated keys, market-aware runtime TTL policies, and
authenticated admin management to reduce repeat broker API calls.

## Requirements

### Requirement: Redis cache configuration
The system SHALL read cache configuration from Pydantic `BaseSettings` (environment / `.env`): `CACHE_ENABLED` (bool, default `true`), `REDIS_URL` (default `redis://localhost:6379/0`), `REDIS_TIMEOUT_SECONDS` (default `1.0`), and the initial cache policy `CACHE_TTL_OPTION_CHAIN_SECONDS` (default `900`), `CACHE_TTL_HISTORICAL_CLOSED_SECONDS` (default `604800`), `CACHE_TTL_HISTORICAL_OPEN_BAR_SECONDS` (default `300`), `CACHE_TTL_HISTORICAL_INTRADAY_SECONDS` (default `300`) and `CACHE_EXTEND_WHEN_MARKET_CLOSED` (default `true`).

#### Scenario: Redis URL from environment
- **WHEN** `.env` contains `REDIS_URL=redis://cache:6379/2`
- **THEN** the cache backend connects to `redis://cache:6379/2`

#### Scenario: Caching disabled
- **WHEN** `CACHE_ENABLED=false`
- **THEN** no Redis connection is opened and every request is served live from the provider without cache headers

### Requirement: Cache lifecycle bound to application lifespan
The system SHALL initialize the Redis client and the `fastapi-cache2` backend during FastAPI `lifespan` startup and SHALL close the Redis client during shutdown. Before startup (or after shutdown) caching SHALL be disabled rather than raising errors.

#### Scenario: Startup with reachable Redis
- **WHEN** the application starts and Redis answers `PING`
- **THEN** caching is enabled and the startup log reports Redis as connected

#### Scenario: Shutdown
- **WHEN** the application shuts down
- **THEN** the Redis connection pool is closed and caching is disabled

#### Scenario: Endpoint called without lifespan
- **WHEN** a cached endpoint is invoked before the lifespan has run (e.g. `TestClient` without context manager)
- **THEN** the request is served live and does not fail

### Requirement: Fail-open on Redis errors
The system MUST NOT fail a request because Redis is unreachable, slow or returns an error. On any Redis error the data SHALL be fetched live from the provider, a single warning SHALL be logged, and Redis SHALL be skipped for a cooldown period (30 s) before it is retried.

#### Scenario: Redis down at startup
- **WHEN** Redis is unreachable at startup
- **THEN** the application starts, logs a warning, and serves cached endpoints live

#### Scenario: Redis fails at runtime
- **WHEN** a Redis read or write raises a connection or timeout error during a request
- **THEN** the response is returned with live provider data and HTTP 200

#### Scenario: Cooldown avoids per-request timeouts
- **WHEN** a Redis error occurred less than 30 s ago
- **THEN** subsequent requests do not contact Redis and are served live immediately

#### Scenario: Recovery
- **WHEN** the cooldown has elapsed and Redis is reachable again
- **THEN** caching resumes without restarting the application

### Requirement: Transparent cache key naming
Cache keys SHALL follow `mdh:{route_path}:{symbol}:{query_params}` where `route_path` is the route template without path parameters joined by `:`, `symbol` is the upper-cased path symbol, and `query_params` is the URL-encoded, alphabetically sorted list of declared, non-empty query parameters (`-` when none). `provider`, `format` and `sec_type` values SHALL be lower-cased to mirror route normalization. Undeclared query parameters SHALL NOT influence the key.

#### Scenario: Option chain key
- **WHEN** `GET /options/spx/chain?provider=Schwab` is requested
- **THEN** the cache key is `mdh:options:chain:SPX:provider=schwab`

### Requirement: Caching applies to all providers with provider-isolated keys
Caching SHALL apply regardless of the provider serving the request. The key SHALL always contain the effective provider: the explicit `provider` query parameter, or, when absent, the current system default for the endpoint's capability (`default_options_provider` for options, `default_price_provider` for prices).

#### Scenario: Implicit default provider
- **WHEN** the default options provider is `schwab` and `GET /options/SPX/chain` is requested
- **THEN** the cache key is `mdh:options:chain:SPX:provider=schwab`

#### Scenario: Explicit and implicit provider share an entry
- **WHEN** the default options provider is `schwab` and `GET /options/SPX/chain` and `GET /options/SPX/chain?provider=schwab` are requested
- **THEN** both requests use the same cache entry

#### Scenario: Default provider changed
- **WHEN** the default options provider changes from `schwab` to `ibkr` in the Admin UI
- **THEN** a subsequent `GET /options/SPX/chain` uses the key `mdh:options:chain:SPX:provider=ibkr` and never returns Schwab data

#### Scenario: No provider configured
- **WHEN** no default provider is configured and no `provider` is given
- **THEN** the request fails with `PROVIDER_NOT_AVAILABLE` and nothing is cached

#### Scenario: Parameter order independence
- **WHEN** `GET /prices/AAPL/history?provider=schwab&interval=1d` and `GET /prices/AAPL/history?interval=1d&provider=schwab` are requested
- **THEN** both resolve to `mdh:prices:history:AAPL:interval=1d&provider=schwab`

#### Scenario: No query parameters
- **WHEN** a cached route without a provider capability mapping is requested without query parameters
- **THEN** the query segment of the key is `-`

#### Scenario: Unknown parameters ignored
- **WHEN** `GET /options/SPX/chain?provider=schwab&_ts=123` is requested
- **THEN** the cache key is `mdh:options:chain:SPX:provider=schwab`

### Requirement: US market session model
The cache policy SHALL use a US equity session model in `America/New_York`: regular session Mon–Fri 09:30–16:00, extended session 04:00–20:00 (used when `extended_hours=true`). After the session end a settle grace of 30 min SHALL apply, during which data counts as still changing. The market counts as **settled** from session end + grace until the next session open (weekends included). Exchange holidays are not modeled; they are treated as trading days, which errs on the side of fresher data.

#### Scenario: Weekday evening
- **WHEN** it is Tuesday 18:00 ET
- **THEN** the market is settled and the next open is Wednesday 09:30 ET

#### Scenario: Weekend
- **WHEN** it is Friday 17:00 ET
- **THEN** the next open is Monday 09:30 ET

#### Scenario: Settle grace
- **WHEN** it is 16:10 ET on a weekday
- **THEN** the market is not yet settled

### Requirement: Option chain caching
`GET /options/{symbol}/chain` SHALL be cached for both JSON and CSV formats. During the session (incl. settle grace) the option-chain TTL (default 900 s) SHALL apply. While the market is settled and the market-closed extension is enabled, the TTL SHALL be the time until the next session open, capped at the closed-range TTL.

#### Scenario: Repeated chain request during session
- **WHEN** the same option chain is requested twice within 15 minutes during the session
- **THEN** the provider is called once and the second response carries `X-FastAPI-Cache: HIT` with an identical body

#### Scenario: Chain cached over the weekend
- **WHEN** a chain is requested Saturday 10:00 ET with the extension enabled
- **THEN** it is cached until Monday 09:30 ET

### Requirement: Bar-state-aware historical prices caching
`GET /prices/{symbol}/history` SHALL be cached for both JSON and CSV formats with a TTL that depends on whether the requested range can still change:

1. **Closed range**: an explicit `end` that lies before the start of the current bar period with a safety margin. Intraday: before today 00:00 ET. `1d`: before yesterday 00:00 ET. `1w`/`1wk`: before the Monday 00:00 ET of the current week minus 1 day. `1mo`: before the first day of the current month 00:00 ET minus 1 day. Such a range SHALL use the closed-range TTL (default 604800 s = 7 days) for every interval.
2. **Open range** (no `end`, or `end` not before the current bar period), market settled and extension enabled: TTL = time until the next session open, capped at the closed-range TTL.
3. **Open range during the session**: daily-or-longer intervals (`1d`, `1w`, `1wk`, `1mo`, missing interval = `1d`) SHALL use the open-bar TTL (default 300 s, aligned with the intraday TTL so that daily+ and intraday charts show the same freshness). Intraday intervals (number + `s`/`m`/`min`/`h`) SHALL use the intraday TTL (default 300 s), capped at the bar length (`1m` → 60 s).

Naive `end` datetimes SHALL be interpreted as UTC. `1m` means minute and `1mo` means month.

#### Scenario: Last year's weekly candles
- **WHEN** `interval=1w&start=2025-01-01&end=2025-12-31` is requested in November 2026
- **THEN** the entry is cached for 7 days

#### Scenario: Yesterday's intraday bars
- **WHEN** `interval=5m` with `end` = yesterday 16:00 ET is requested today
- **THEN** the closed-range TTL applies

#### Scenario: Daily chart during session
- **WHEN** `interval=1d` without `end` is requested Wednesday 11:00 ET
- **THEN** the entry is cached for the open-bar TTL (300 s), so the forming daily bar is at most 5 min old

#### Scenario: Daily chart overnight
- **WHEN** `interval=1d` without `end` is requested Wednesday 20:00 ET with the extension enabled
- **THEN** the entry is cached until Thursday 09:30 ET

#### Scenario: Extension disabled
- **WHEN** the market-closed extension is disabled and `interval=1d` without `end` is requested Saturday
- **THEN** the open-bar TTL (300 s) applies

#### Scenario: One-minute bars capped
- **WHEN** `interval=1m` without `end` is requested during the session with intraday TTL 300 s
- **THEN** the entry is cached for 60 s

#### Scenario: Extended hours session
- **WHEN** `interval=5m&extended_hours=true` is requested at 18:00 ET on a weekday
- **THEN** the session TTL applies (extended session runs until 20:00 ET), not the market-closed extension

#### Scenario: Minute is not month
- **WHEN** `interval=1m` is requested
- **THEN** the intraday rules apply, while `interval=1mo` follows the daily-or-longer rules

### Requirement: Runtime-configurable cache policy
The cache policy SHALL be adjustable at runtime via the Admin API/UI without restart and SHALL be persisted in `system_settings`. The stored keys are `cache_ttl_option_chain_seconds`, `cache_ttl_historical_closed_seconds`, `cache_ttl_historical_open_bar_seconds`, `cache_ttl_historical_intraday_seconds` and `cache_extend_when_market_closed`. Environment values serve as defaults when no stored value exists. TTLs SHALL be integers from 0 to 2592000 (30 days). `0` disables caching for that policy, including its market-closed extension. Changes SHALL apply to entries written after the change; existing entries keep their remaining lifetime. Each replica SHALL pick up stored changes within 30 s.

#### Scenario: Change TTL in Admin UI
- **WHEN** an admin sets the option-chain TTL to 300 s
- **THEN** new option-chain entries written during the session expire after 300 s, without restarting the application

#### Scenario: TTL zero disables a policy
- **WHEN** the intraday TTL is set to 0
- **THEN** open-range intraday history responses are served live and not written to Redis, at any time of day

#### Scenario: Invalid TTL
- **WHEN** an admin submits a negative TTL or one above 2592000
- **THEN** the API responds with 422 and stored values are unchanged

#### Scenario: Env default
- **WHEN** no value is stored in `system_settings`
- **THEN** the corresponding `CACHE_*` environment value is used

### Requirement: Accurate Cache-Control header
On a cache MISS the `Cache-Control: max-age` header SHALL equal the effective TTL used for the Redis write (not a static decorator value). On a HIT it SHALL equal the remaining TTL. When the effective TTL is 0, the response SHALL carry `Cache-Control: no-store`.

#### Scenario: Header follows runtime TTL
- **WHEN** the option-chain TTL was changed to 300 s and a chain request misses the cache
- **THEN** the response carries `Cache-Control: max-age=300`

#### Scenario: CSV served from cache
- **WHEN** a `format=csv` history request is repeated
- **THEN** the cached response has the same body, `text/csv` media type and `Content-Disposition` header as the original

### Requirement: Errors are never cached
Provider errors and validation errors SHALL NOT be stored in the cache.

#### Scenario: Provider unavailable
- **WHEN** the provider raises `PROVIDER_NOT_AVAILABLE` for a chain request
- **THEN** the error response is returned and the next identical request calls the provider again

### Requirement: Client-controlled bypass
Clients SHALL be able to bypass the cache: `Cache-Control: no-cache` forces a live fetch and refreshes the entry; `Cache-Control: no-store` forces a live fetch without touching the cache.

#### Scenario: Forced refresh
- **WHEN** a request carries `Cache-Control: no-cache`
- **THEN** the provider is called and the cache entry is overwritten with the fresh result

### Requirement: Admin cache status endpoint
`GET /api/admin/cache` SHALL require admin authentication and return the cache state (`disabled` | `connected` | `unavailable`), the redacted Redis URL (no password), the effective cache policy (with its env defaults), the current market state (`session` | `settle_grace` | `settled`) with the next open timestamp, Redis memory usage (`used_memory`, `maxmemory`), and the number of keys per cached endpoint (`options_chain`, `historical_prices`) counted via non-blocking `SCAN`.

#### Scenario: Status with Redis connected
- **WHEN** an admin requests `GET /api/admin/cache` and Redis is reachable
- **THEN** the response contains `state: "connected"` and key counts per endpoint

#### Scenario: Status without Redis
- **WHEN** Redis is unreachable
- **THEN** the response contains `state: "unavailable"` and HTTP 200 with null key counts

#### Scenario: Unauthenticated
- **WHEN** the request has no valid admin token
- **THEN** the API responds with 401

### Requirement: Admin cache clear endpoint
`POST /api/admin/cache/clear` SHALL require admin authentication and a body with `confirm: true`. It SHALL accept an optional `scope` (`all` default, `options_chain`, `historical_prices`) and an optional `provider` filter. It SHALL delete only matching `mdh:*` keys using `SCAN` + `UNLINK` (never `KEYS`/`FLUSHDB`), return the number of deleted keys, and write an audit log entry with the admin principal, scope, provider and count.

#### Scenario: Clear everything
- **WHEN** an admin posts `{"confirm": true}`
- **THEN** all `mdh:*` keys are removed and `deleted` reports the count

#### Scenario: Clear one provider's option chains
- **WHEN** an admin posts `{"confirm": true, "scope": "options_chain", "provider": "schwab"}`
- **THEN** only `mdh:options:chain:*` keys whose provider is `schwab` are removed

#### Scenario: Missing confirmation
- **WHEN** the body lacks `confirm: true`
- **THEN** the API responds with 400 and deletes nothing

#### Scenario: Redis unavailable
- **WHEN** Redis is unreachable or caching is disabled
- **THEN** the API responds with 503 and a descriptive message

#### Scenario: Foreign keys untouched
- **WHEN** the Redis database contains keys without the `mdh:` prefix
- **THEN** those keys are not deleted

### Requirement: Admin cache policy update endpoint
`PUT /api/admin/cache/policy` SHALL require admin authentication and accept any subset of `option_chain_seconds`, `historical_closed_seconds`, `historical_open_bar_seconds`, `historical_intraday_seconds` (0–2592000) and `extend_when_market_closed` (bool). It SHALL persist the values in `system_settings`, apply them immediately on the handling replica, write an audit log entry, and return the effective policy. The endpoint SHALL work even when Redis is unavailable.

#### Scenario: Partial update
- **WHEN** an admin sends `{"historical_intraday_seconds": 120}`
- **THEN** only the intraday TTL changes and the response lists the full effective policy

#### Scenario: Toggle extension
- **WHEN** an admin sends `{"extend_when_market_closed": false}`
- **THEN** subsequent writes outside the session use the session TTLs

### Requirement: Admin UI cache management
The Settings page SHALL show a "Response Cache" card with state, Redis URL, memory usage and key counts. It SHALL show the current market state (session / settle grace / settled until next open). It SHALL include an editable policy form: option chain, closed ranges, open bar (daily+), intraday, each with human-readable hints (e.g. "= 5 min", "= 7 d"), and a switch "Keep entries until next market open while the market is closed" with a note that the session model is US (09:30–16:00 ET) and should be disabled for non-US symbols. The form SHALL note that changes apply to new entries only and SHALL have a Save button. The card SHALL also have a danger-zone "Clear cache…" button. The button SHALL open a confirmation dialog containing a warning that all following requests hit the broker APIs live (rate-limit risk), scope and provider selectors, and an acknowledgement checkbox. The destructive "Clear cache" button SHALL stay disabled until the checkbox is ticked.

#### Scenario: Confirm via checkbox
- **WHEN** the admin opens the dialog, ticks the acknowledgement and clicks "Clear cache"
- **THEN** the clear endpoint is called with `confirm: true`, a success message shows the deleted count, and the status card refreshes

#### Scenario: Not acknowledged
- **WHEN** the checkbox is not ticked
- **THEN** the "Clear cache" button is disabled

#### Scenario: Cache not available
- **WHEN** the state is `disabled` or `unavailable`
- **THEN** the "Clear cache…" button is disabled and the card explains why

### Requirement: Docker Compose Redis service
`docker-compose.yml` SHALL provide a `redis` service (`redis:7-alpine`) on the internal network without host port exposure. It SHALL persist RDB snapshots (`--save 300 1 --save 60 1000`, `--appendonly no`) to a named volume `redis-data` mounted at `/data`, bound memory (`--maxmemory ${REDIS_MAXMEMORY:-256mb}`, `--maxmemory-policy allkeys-lru`), and include a `redis-cli ping` healthcheck. The MDH service SHALL receive `REDIS_URL` (default `redis://redis:6379/0`) and SHALL start even if Redis is unhealthy.

#### Scenario: Compose up
- **WHEN** `docker compose up` is run
- **THEN** Redis starts, MDH connects via `redis://redis:6379/0`, and the startup banner shows the cache as connected

#### Scenario: Warm cache after restart
- **WHEN** `docker compose down && docker compose up` is run and the cached entries have not expired yet
- **THEN** the entries are loaded from the RDB snapshot and served as HITs without provider calls

#### Scenario: Expired entries not resurrected
- **WHEN** Redis restarts after an entry's TTL has passed
- **THEN** the entry is not served

#### Scenario: Memory bound
- **WHEN** the cache reaches `maxmemory`
- **THEN** Redis evicts least-recently-used entries instead of rejecting writes

#### Scenario: Redis container stopped
- **WHEN** the `redis` container is stopped while MDH runs
- **THEN** MDH keeps serving requests live and resumes caching once Redis is back
