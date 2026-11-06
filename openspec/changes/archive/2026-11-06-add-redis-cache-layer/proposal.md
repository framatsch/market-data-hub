## Why

The Next.js dashboard polls option chains and historical candles repeatedly. Every request currently goes straight to the broker APIs (Schwab ~120 req/min, Finnhub 60 req/min, IBKR pacing limits), so dashboard refreshes burn rate limits and add multi-second latency for data that barely changes (open interest is daily, daily closes are fixed intraday). A shared Redis cache in front of the two heaviest read endpoints protects the providers and gives the dashboard sub-millisecond repeat reads, including across multiple replicas.

## What Changes

- Add `fastapi-cache2[redis]` (async `redis.asyncio` client) as a runtime dependency.
- Initialize the cache backend in the FastAPI `lifespan` and close the Redis connection on shutdown.
- New settings in `app/config.py` (Pydantic `BaseSettings`, `.env`): `CACHE_ENABLED`, `REDIS_URL`, `REDIS_TIMEOUT_SECONDS`, `CACHE_TTL_OPTION_CHAIN_SECONDS` (900), `CACHE_TTL_HISTORICAL_CLOSED_SECONDS` (604800), `CACHE_TTL_HISTORICAL_OPEN_BAR_SECONDS` (300), `CACHE_TTL_HISTORICAL_INTRADAY_SECONDS` (300), `CACHE_EXTEND_WHEN_MARKET_CLOSED` (true). These are initial defaults and can be changed at runtime in the Admin UI (persisted in `system_settings`, no restart).
- Bar- and market-state-aware TTLs (new `app/market_hours.py`, US session model). Ranges with only closed bars are cached for 7 days. Ranges containing the forming bar are cached for 5 min during the session (intraday additionally capped at the bar length, so `1m` → 60 s); all charts are thus at most 5 min behind. Outside the session (after close + 30 min grace, weekends) they are cached until the next market open. The extension also applies to option chains and can be switched off.
- Custom key builder producing transparent keys: `mdh:{route_path}:{symbol}:{query_params}` (e.g. `mdh:options:chain:SPX:provider=schwab`).
- Declarative `@cache(...)` on `GET /options/{symbol}/chain` and `GET /prices/{symbol}/history` (TTL policy below; replaces the originally requested fixed 15 min / 12 h). Caching applies to **all providers**. The *effective* provider (explicit `provider` param, otherwise the configured system default) is always part of the key, so entries never mix providers and changing the default provider never serves another provider's data.
- Admin API `GET /api/admin/cache` (status, memory, key counts, TTLs), `PUT /api/admin/cache/policy` (runtime TTLs + market-closed switch) and `POST /api/admin/cache/clear` (scope by endpoint and/or provider, requires `confirm: true`, audit-logged).
- Admin UI: "Response Cache" card on the Settings page with status, an editable TTL form and a danger-zone "Clear cache" dialog (warning, scope selection, mandatory acknowledgement checkbox).
- Fail-open behavior: Redis outages never fail a request; data is fetched live from the provider and Redis is retried after a short cooldown.
- CSV responses of the two endpoints are returned as a buffered `Response` instead of `StreamingResponse` so they can be cached too (same body, headers and media type for clients).
- Responses gain `X-FastAPI-Cache: HIT|MISS`, `Cache-Control: max-age=<ttl>` and `ETag` headers (JSON responses).
- `docker-compose.yml` gets a `redis` service (`redis:7-alpine`, RDB snapshots on volume `redis-data` for a warm cache after restarts, `maxmemory 256mb` + LRU eviction, healthcheck, internal network only) and MDH gets `REDIS_URL=redis://redis:6379/0`; `.env.example` documents the new variables.

## Capabilities

### New Capabilities
- `response-caching`: Redis-backed, fail-open response caching for read-heavy market data endpoints, including key naming convention, TTL policy and lifecycle management.

### Modified Capabilities
<!-- None: endpoint request/response contracts are unchanged; caching is additive. -->

## Impact

- **Code**: new `app/cache.py`; `app/main.py` (lifespan); `app/config.py`; `app/api/routes_options.py`; `app/api/routes_prices.py`; `app/api/routes_admin.py` (cache endpoints); `admin/src/pages/SettingsPage.tsx` + new `admin/src/components/CacheCard.tsx`; `admin/src/types.ts`; `tests/conftest.py`; new `tests/unit/test_cache.py`, `tests/unit/test_admin_cache_routes.py`.
- **Dependencies**: `fastapi-cache2==0.2.x`, which pulls `redis>=4.2,<5` and `pendulum`.
- **Infrastructure**: a Redis instance (docker-compose `redis` service; for Kubernetes a Redis Deployment/Service outside this repo is required to benefit from caching, but not to run).
- **API**: no contract changes. Freshness changes: during the session, chain data may be up to 15 min old, forming bars (daily+ and intraday) at most 5 min or one bar. Outside the session, data is held until the next open; closed ranges are held up to 7 days. Clients can force a refresh with `Cache-Control: no-cache`.
- **Not covered**: MCP tools call the services directly and stay uncached.
