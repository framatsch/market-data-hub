## 1. Setup

- [x] 1.1 Add `fastapi-cache2[redis]>=0.2.2` via `uv add` (updates `pyproject.toml` + `uv.lock`)
- [x] 1.2 Add `CACHE_ENABLED`, `REDIS_URL`, `REDIS_TIMEOUT_SECONDS`, `CACHE_TTL_OPTION_CHAIN_SECONDS`, `CACHE_TTL_HISTORICAL_CLOSED_SECONDS`, `CACHE_TTL_HISTORICAL_OPEN_BAR_SECONDS`, `CACHE_TTL_HISTORICAL_INTRADAY_SECONDS`, `CACHE_EXTEND_WHEN_MARKET_CLOSED` to `app/config.py`
- [x] 1.3 Document the new variables (incl. `REDIS_MAXMEMORY`) in `.env.example`

## 2. Docker Compose

- [x] 2.1 Add `redis` service: `redis:7-alpine`, `--save 300 1 --save 60 1000 --appendonly no`, `--maxmemory ${REDIS_MAXMEMORY:-256mb} --maxmemory-policy allkeys-lru`, `redis-cli ping` healthcheck, `market-data-hub` network, no host port
- [x] 2.2 Add named volume `redis-data` mounted at `/data`
- [x] 2.3 Pass `REDIS_URL: ${REDIS_URL:-redis://redis:6379/0}` and `CACHE_ENABLED` to `market-data-hub`; add `depends_on: redis: condition: service_started`
- [x] 2.4 Verify `docker compose config`, `docker compose up` (banner shows cache connected), `docker compose stop redis` (MDH keeps serving), `down && up` (entries still HIT) — isolated real Redis harness, JSON/CSV for both routes, fake market services (no broker access)

## 3. Cache Module (`app/cache.py`)

- [x] 3.1 Disabled-by-default `FastAPICache` initialization at import
- [x] 3.0 Create `app/market_hours.py`: US session model (ET, regular 09:30–16:00, extended 04:00–20:00, 30 min settle grace), `market_state(now, extended)`, `next_open(now, extended)`, `current_period_start(interval, now)`, interval parsing (`1m` minute vs `1mo` month, bar length)
- [x] 3.2 `CachePolicy`: env defaults, `system_settings` overrides (30 s refresh), validation 0–2592000; `resolve(route, params, now)` implementing closed range → 7 d, settled + extension → until next open (capped), session → open-bar / intraday (capped at bar length); option chain session vs. extension
- [x] 3.3 `FailOpenRedisBackend`: error swallowing, single warning, 30 s cooldown, recovery log; `set()` uses the policy TTL (skip on 0)
- [x] 3.4 `mdh_key_builder` (`mdh:{route_path}:{symbol}:{query_params}`, declared params only, normalization, effective provider from registry defaults)
- [x] 3.5 `MdhJsonCoder` supporting envelopes and buffered `Response` objects; local library-delegating `cache` adapter copies injected cache headers onto CSV responses on MISS/HIT
- [x] 3.6 `CacheControlMiddleware` (pure ASGI): rewrite `Cache-Control` on MISS to the effective TTL, `no-store` for 0
- [x] 3.7 `setup_cache()` / `shutdown_cache()` (ping, redacted URL logging, pool close)
- [x] 3.8 `cache_status()` (state, memory via `INFO memory`, key counts via `SCAN`) and `clear_cache(scope, provider)` (`SCAN` + `UNLINK`, provider filter on parsed query segment)

## 4. API Integration

- [x] 4.1 Call `setup_cache()` / `shutdown_cache()` in `app/main.py` lifespan, register `CacheControlMiddleware`, show cache state in the startup banner
- [x] 4.2 `@cache(expire=settings.CACHE_TTL_OPTION_CHAIN_SECONDS)` on `GET /options/{symbol}/chain`; CSV as buffered `Response`
- [x] 4.3 `@cache(expire=settings.CACHE_TTL_HISTORICAL_OPEN_BAR_SECONDS)` on `GET /prices/{symbol}/history`; CSV as buffered `Response`
- [x] 4.4 `GET /api/admin/cache`, `PUT /api/admin/cache/policy` (422 on invalid, audit log, works without Redis), `POST /api/admin/cache/clear` (`confirm` guard → 400, Redis unavailable → 503, audit log) in `app/api/routes_admin.py`

## 5. Admin UI

- [x] 5.1 Add `CacheStatus`, `CachePolicy`, `CacheClearResult` types to `admin/src/types.ts`
- [x] 5.2 Create `admin/src/components/CacheCard.tsx`: state chip, market state (session / grace / settled until …), Redis URL, memory bar (`used`/`max`), key counts
- [x] 5.3 Policy form: four number fields (option chain, closed ranges, open bar daily+, intraday) with readable hints (`= 5 min`, `= 7 d`), "0 = not cached" hint, switch "Keep until next market open while closed" with US-session / non-US note, "applies to new entries only" note, Save → `PUT /api/admin/cache/policy`
- [x] 5.4 Clear dialog: warning alert, scope + provider selects, acknowledgement checkbox, red button disabled until ticked, success snackbar with deleted count, refetch status
- [x] 5.5 Embed `CacheCard` in `SettingsPage.tsx`; run `npm run lint` and `npm run build` (both pass; 28 existing admin lint errors fixed after user approval)

## 6. Tests

- [x] 6.1 Default `CACHE_ENABLED=false` in `tests/conftest.py` for hermetic tests
- [x] 6.2 Key builder: example key, ordering, unknown params, normalization, implicit default provider, URL-encoding
- [x] 6.3 Market hours (frozen clock): session / grace / settled, next open incl. weekend, extended session, period starts for 1m/1h/1d/1w/1mo
- [x] 6.3a Cache policy: closed range (last year weekly, yesterday intraday), open range in session (1d → 300, 5m → 300, 1m → 60 cap), settled + extension (until next open, capped), extension off, chain weekend, 0 skips write, naive `end` as UTC, env default vs stored override, validation bounds
- [x] 6.4 HIT/MISS for chain and history (JSON + CSV) with a fake backend; errors not cached; `Cache-Control` matches runtime TTL
- [x] 6.5 Fail-open: failing Redis → HTTP 200 live data, cooldown skips Redis, recovery; lifespan with Redis down
- [x] 6.6 Admin cache routes: auth required, status states, TTL update (partial, 422), `confirm` guard, scope/provider filtering, foreign keys untouched, 503 when unavailable
- [x] 6.7 Run `uv run ruff check app/`, mypy, and the full pytest suite (394 passed, 20 skipped; app lint and mypy pass)

## 7. Docs

- [x] 7.1 README: Redis/caching section (env vars, key format, TTL policy + Admin UI, bypass headers, clear cache, compose persistence)
- [x] 7.2 CHANGELOG `Unreleased` entry
