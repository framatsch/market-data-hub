## Context

MDH is a FastAPI service aggregating IBKR, LSEG, Schwab, Finnhub, Polygon and Prixe. The only cache today is LSEG's in-process 5 s quote cache. The Next.js dashboard hits `GET /options/{symbol}/chain` (GEX views) and `GET /prices/{symbol}/history` (candles) repeatedly, which is the dominant source of broker calls. MDH runs in Docker / Kubernetes, possibly with several replicas, so an in-process cache would not be shared.

Note on naming: the original request referenced `/quotes/{symbol}/historical` and `routes/quotes.py`; the existing equivalent is `GET /prices/{symbol}/history` in `app/api/routes_prices.py`. No new route is introduced.

## Goals / Non-Goals

**Goals:**
- Shared Redis cache for the two read-heavy endpoints with per-endpoint TTLs.
- Declarative usage (`@cache(expire=...)`) at the router level.
- Human-readable, deterministic keys (`mdh:options:chain:SPX:provider=schwab`).
- Fail-open: Redis is an optimization, never a dependency for availability.

**Non-Goals:**
- Caching `/prices/{symbol}/last`, option quotes, company or news endpoints.
- Caching MCP tool calls (they invoke services directly, not the routes).
- Automatic invalidation on provider-config changes (not needed thanks to D7; manual clear via D8).
- Per-provider cache opt-out (all providers have rate limits or pacing; can be added later via a setting).
- Redis Cluster / Sentinel topology (the backend supports Cluster, but it is not configured here).

## Decisions

### D1: `fastapi-cache2` with `redis.asyncio`
Use `fastapi-cache2[redis]` 0.2.x, as requested. It provides the `@cache` decorator, HIT/MISS headers, ETag/304 handling and honors `Cache-Control: no-cache/no-store`.
*Alternatives*: `aiocache` (no FastAPI-aware decorator), hand-rolled middleware (more code, no gain). *Constraint*: 0.2.x pins `redis<5`, which resolves to `redis 4.6` and conflicts with nothing in `uv.lock`.

### D2: Fail-open backend with circuit breaker (`FailOpenRedisBackend`)
`fastapi-cache2` already catches exceptions around `get_with_ttl`/`set`, but it logs a full traceback per request and still waits for the socket timeout on every call. A `RedisBackend` subclass catches all errors itself, logs one warning, and skips Redis for 30 s (`time.monotonic()` based). Short `socket_connect_timeout`/`socket_timeout` (`REDIS_TIMEOUT_SECONDS`, default 1 s) bound the worst-case latency of the first failing call.
*Alternative*: rely on library behavior only → log flooding and +timeout latency on every request during outages.

### D3: Always-initialized `FastAPICache`
The decorator asserts that `FastAPICache.init()` has run. `app/cache.py` therefore initializes a disabled state at import time (`enable=False`). The lifespan resets and re-initializes with the Redis backend, and shutdown resets to disabled again. This keeps tests that use `TestClient(app)` without lifespan, as well as the disabled mode, working without special cases.

### D4: Key builder from route metadata
`mdh_key_builder` uses `request.scope["route"].path` (the template, e.g. `/options/{symbol}/chain`). It drops `{...}` segments to get `options:chain` and upper-cases `path_params["symbol"]`. For the query part it uses only parameters declared by the route (`route.dependant.query_params`), skipping empty values, lower-casing `provider`/`format`/`sec_type`, sorting, and URL-encoding with `urlencode`. URL-encoding means values never contain raw `:`/`&`/`=`, so keys are unambiguous (ISO datetimes become `start=2026-01-01T00%3A00%3A00`). When there are no parameters the segment is `-`. The global prefix `mdh` comes from `FastAPICache.init(prefix="mdh")`.
*Alternative*: hashing kwargs (library default) → opaque `md5` keys, which goes against the transparency requirement.

### D5: Coder that preserves JSON and CSV responses
`MdhJsonCoder(JsonCoder)` keeps the library's JSON encoding for envelopes. Pydantic models go through `jsonable_encoder` (JSON mode), so Decimals stay strings exactly as in uncached responses. The coder also serializes plain `Response` objects (body, status, media type, `Content-Disposition`) under a `_mdh_response` marker. The CSV branches therefore return `Response(content=csv)` instead of `StreamingResponse`: the CSV is already fully materialized in memory, and a streaming body cannot be encoded synchronously. Clients see no change in body, media type or headers.

**CSV header adapter (approved implementation adjustment)**: `fastapi-cache2` updates FastAPI's injected `Response`, but FastAPI does not merge that object's headers into a concrete `Response` returned by the endpoint or coder. A small local `cache` adapter delegates to the library decorator and copies only `Cache-Control`, `ETag` and `X-FastAPI-Cache` onto returned buffered responses, on MISS and HIT. This preserves the declarative decorator, JSON behavior, CSV metadata and 304 handling, and lets `CacheControlMiddleware` see and rewrite CSV MISS headers too.

### D6: Bar-state-aware runtime TTL policy, applied at write time
**Why not a fixed 12 h for history**: closed bars never change, so 12 h is far too short for them (a 2025 weekly chart could be cached for days). The forming bar, however, changes all session long. A 12 h TTL on "last 30 days until now" would serve a daily bar from 09:45 at 15:00. The original premise ("daily closes don't change intraday") only holds for already closed days.

**Why not per-bar (split) caching**: the response is cached as a whole, and the typical dashboard request (no `end`) always contains the forming bar. Caching closed bars separately and fetching only the tail still needs one provider call per refresh, so it saves no rate limit, only payload. It would add gap handling, holiday handling and split adjustments. The rate-limit-relevant lever is the TTL of the whole response, chosen by bar state and market state.

**Resolution** (`CachePolicy.resolve(route, params, now)`), applied **from the cache key** inside `FailOpenRedisBackend.set()`, because `@cache(expire=...)` is fixed at import:
- `mdh:options:chain:*` → session: `option_chain` (900 s). Settled market with extension on: seconds until next open, capped at `historical_closed`.
- `mdh:prices:history:*` → parse `interval`, `end` and `extended_hours` from the URL-encoded query segment (it contains no raw `:`, so `rsplit(":", 1)` is safe):
  1. explicit `end` before the current bar period minus margin → `historical_closed` (7 d). Margins: intraday < today 00:00 ET; `1d` < yesterday 00:00 ET; `1w`/`1wk` < Monday 00:00 ET − 1 d; `1mo` < 1st of month 00:00 ET − 1 d. The margin absorbs time-zone ambiguity (naive `end` = UTC) and late provider corrections of the last bar.
  2. open range + settled + extension → until next open, capped at `historical_closed`.
  3. open range in session → `historical_open_bar` (300 s; same as intraday because the forming daily bar carries the same last price as the latest 5m bar, so charts side by side never diverge by more than 5 min) for `1d`/`1w`/`1wk`/`1mo`; `historical_intraday` (300 s) for `^\d+(s|m|min|h)$`, capped at the bar length.
- TTL `0` on the governing policy → the write is skipped (no extension either).
- unknown keys → the decorator's `expire` (fallback).

**Session model** (`app/market_hours.py`, pure functions, `zoneinfo`): US equities, `America/New_York`, Mon–Fri 09:30–16:00 regular and 04:00–20:00 extended (when `extended_hours=true`), plus a 30 min settle grace after session end. Late prints, official closes and SPX options trading until 16:15 make the first minutes after the bell unreliable. Holidays are not modeled and count as trading days, so the error is always toward fresher data. *Alternative*: `exchange_calendars`/`pandas_market_calendars`. Rejected for now as a heavy dependency for a marginal gain; can be added later behind the same function.

**Non-US symbols**: the session model is US-only. For e.g. LSEG `VOD.L`, 03:00–09:30 ET would count as "settled" although London trades. The admin can disable the market-closed extension globally (`extend_when_market_closed`), which falls back to the session TTLs at all times. Closed-range caching stays correct regardless of exchange because of its 1-day margin.

The decorators keep env values as `expire` (`CACHE_TTL_OPTION_CHAIN_SECONDS`, `CACHE_TTL_HISTORICAL_OPEN_BAR_SECONDS`), so the declarative `@cache` usage stays as requested.

**Storage**: `system_settings` (existing `SettingsRepository`, same pattern as the default providers). Env `CACHE_*` values are the defaults. The policy keeps an in-process copy, updated immediately on `PUT /api/admin/cache/policy` and re-read from SQLite at most every 30 s, so other replicas that share `keys.db` converge without restart. The max TTL is 30 days.
*Alternative*: storing TTLs in Redis. Rejected because TTL config would vanish with the cache and be unavailable exactly when Redis is down.

**Cache-Control header**: on a MISS, `fastapi-cache2` writes `max-age=<decorator expire>`, which would be wrong after a runtime change. Browsers would then cache longer or shorter than the server. A small pure-ASGI middleware (`CacheControlMiddleware`) rewrites `Cache-Control` on `X-FastAPI-Cache: MISS` responses. It uses the same policy, with the route template from `scope["route"]` and the query string from the scope. For TTL 0 it sets `no-store`. HITs already carry the real remaining TTL from Redis.

**Existing entries** keep their remaining TTL after a change (no rewrite or scan). The UI says so and points to "Clear cache" if the change must apply immediately.

### D7: Cache all providers, key on the *effective* provider
Caching sits at the route level, so it automatically covers every provider (Schwab, IBKR, LSEG, Polygon, Prixe, Finnhub). They all have rate limits or pacing rules, so excluding any of them gains nothing. When `provider` is absent, the key builder fills in the registry's current default for the route's capability (first path segment `options` → `default_options_provider`, `prices` → `default_price_provider`). As a result:
- `?provider=schwab` and the implicit default `schwab` share one entry (better hit rate);
- switching the default provider in the Admin UI immediately routes to new keys, so there is no stale cross-provider data and no flush is needed;
- the provider becomes a reliable key segment, which makes per-provider clearing (D8) possible.
If no default is configured, the key carries no provider. The request then fails with `PROVIDER_NOT_AVAILABLE`, and errors are never cached.
*Alternative*: flushing on every default/provider config change. That adds coupling to the admin routes and still races with in-flight requests.

### D8: Admin clear endpoint and UI confirmation pattern
- **API**: `GET /api/admin/cache` (status/counts) and `POST /api/admin/cache/clear` with `{confirm: true, scope?, provider?}`. The endpoint uses POST with a body rather than DELETE because it acts on a filtered set and carries an explicit confirmation flag. It deletes with `SCAN MATCH mdh:<route>:*` + `UNLINK` in batches of 500. The library's `FastAPICache.clear()` uses a blocking `KEYS` Lua script, and `FLUSHDB` would wipe foreign keys in a shared Redis. The provider filter is applied in Python by parsing the URL-encoded query segment, so `schwab` can never match a prefix such as `schwabx`. The server-side `confirm` flag guards against accidental API calls (scripts, curl). Every clear writes an `audit_log` event.
- **UI**: a dialog with a warning, an **acknowledgement checkbox** and a red button. *Alternative considered*: typing a phrase such as "clear cache". That level of friction suits irreversible operations (deleting credentials). Clearing the cache loses no data and self-heals within one request per key; the real risk is a burst of live provider calls. A checkbox that names exactly this consequence plus a disabled-until-ticked button gives the right friction. Scope and provider selectors let the admin clear just what is needed (e.g. only Schwab chains after a re-auth) instead of everything.

### D9: Docker Compose Redis
`redis:7-alpine` with **RDB snapshots** `--save 300 1 --save 60 1000 --appendonly no` on a named volume `redis-data:/data`. Redis stores absolute expiry timestamps, so a restored snapshot never resurrects expired entries. The benefit is a warm cache after `docker compose down/up` or a Redis restart, which avoids a burst of live broker calls (the very thing the cache exists to prevent). At most ~5 min of entries are lost on a crash, which is harmless for a cache, so AOF is unnecessary I/O. `--maxmemory ${REDIS_MAXMEMORY:-256mb} --maxmemory-policy allkeys-lru` keeps memory bounded. A typical dashboard needs ~15–30 MB (an SPX chain for one expiry is ~300–600 KB, a year of daily bars ~50 KB), so 256 MB leaves ample headroom. The service also has a `redis-cli ping` healthcheck, and no host port (internal `market-data-hub` network only, no auth needed). MDH uses `depends_on: redis: condition: service_started`, not `service_healthy`, so an unhealthy Redis never blocks MDH startup. This matches the fail-open principle. `REDIS_URL` defaults to `redis://redis:6379/0` and can be overridden from `.env`.

## Risks / Trade-offs

- [Closed-range entries (7 d) miss split/dividend re-adjustments by the provider] → Admin "Clear cache" by scope/provider after corporate actions; TTL adjustable.
- [Holidays count as trading days] → Only causes extra refreshes on holidays, never stale data.
- [US session model wrong for non-US symbols] → Global switch to disable the market-closed extension; see D6.
- [System clock skew changes session detection] → Containers use NTP-synced host time; the 30 min grace absorbs minor skew.
- [TTL changes don't affect existing entries] → UI hint plus "Clear cache" with scope.
- [Replicas without a shared `keys.db` keep their own TTL settings] → Same limitation as today's default-provider settings; documented.
- [RDB fork briefly needs copy-on-write memory] → Negligible at ≤256 MB.
- [Default `expiry`/`start`/`end` are computed in the handler, so a parameterless request caches "today" / "last 30 days" for the TTL] → Acceptable within TTL; around midnight a chain may refer to the previous day for at most 15 min.
- [Provider re-authenticated or misbehaving data cached for up to TTL] → Admin UI clear with provider filter (D8).
- [Model shape changes across deployments may be served from old entries for up to 12 h] → Clear via Admin UI after breaking response-model changes.
- [Clearing the whole cache causes a burst of live provider calls] → Warning in dialog, scope/provider filters, providers' own rate limiters.
- [`fastapi-cache2` ETag uses Python `hash()` (process-randomized), so ETags differ between replicas] → Only weakens 304 revalidation; correctness unaffected.
- [Stampede: concurrent misses for the same key all call the provider] → The providers' existing rate limiters bound this; single-flight locking is out of scope.

## Migration Plan

1. Deploy Redis (docker-compose `redis` service; in Kubernetes a Redis Deployment/Service) and set `REDIS_URL`.
2. Deploy MDH. If Redis is missing, MDH still runs (fail-open) and logs a warning.
3. Rollback: set `CACHE_ENABLED=false` (no code rollback needed).

## Open Questions

- Kubernetes: add a Redis Deployment/Service to the cluster manifests (outside this repo)?
