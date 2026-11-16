## Why

Daily candles and daily implied-volatility points of a closed trading day never change again, yet MDH keeps them only in the Redis response cache, where an entry is one whole response under one query string. Every expiry therefore reloads the complete range from the provider (620 days of bars per symbol for VisioTrade, about 380 days of IV history for every IV Rank). The production log of 14–16 November 2026 shows the cost: 39 daily-history requests with a median of 0.7 s and up to 1.8 s each, three of them rejected with 503 by the Schwab rate limiter during one burst, and IV Rank requests that took 1.75 s when the IB Gateway answered and 12 s until a 503 when it did not. A durable store for closed days makes these requests independent of the provider for everything except the newest day, and lets IV Rank be answered while a provider is down.

The same holds for weekly, four-hour and hourly bars that chart clients load: a closed bar does not change, and providers limit how far back intraday bars reach, so a store also keeps bars a provider no longer delivers. Which of these intervals are worth storing differs per provider, so it is a setting.

Clients also cannot tell how old the data in a response is: a cache hit looks exactly like a live answer. VisioTrade stamps chains with its own request time, so its "as of" can be up to one cache lifetime wrong.

## What Changes

- New optional PostgreSQL store for **price bars** of the intervals `1h`, `4h`, `1d` and `1w` and for **daily IV points**, keyed by canonical symbol, provider, interval and (for IV) tenor and instrument. Only closed bars and closed trading days are stored.
- New provider setting `history_store_intervals`: the intervals whose bars are stored for that provider. Default `["1d"]`, editable in the provider details of the Admin UI, effective without a restart. The store keeps what the price service returns; it does not compute an interval a provider does not deliver (that is `add-derived-price-intervals`).
- `DATABASE_URL` switches the store on. Without it MDH needs no PostgreSQL and behaves as today, so a local Docker Compose setup keeps working with SQLite and Redis only. Credentials, provider configuration and system settings stay in SQLite (`KEYS_DB_PATH`) in either case.
- `GET /prices/{symbol}/history` with an interval stored for the effective provider reads closed bars from the store and asks the provider only for what is missing: the bars after the stored range (including the forming bar) or the bars before it. Response shape and bar values stay the same.
- `GET /volatility/{symbol}/history` reads closed days from the store in the same way.
- `GET /volatility/{symbol}/stats` computes IV Rank and IV Percentile from the stored points instead of a full provider download per request.
- Revision detection: every tail synchronisation re-reads the five newest stored bars; a difference in an older bar (split or dividend adjustment) reloads the whole stored range of that series.
- When the provider fails and the store holds the requested closed bars, the stored data is returned with `meta.stale = true` instead of an error. Such responses are not written to the response cache.
- Daily price bars only: when the requested provider fails and has no stored bars for the range, stored daily bars of another provider for the same symbol are returned, marked stale and with `meta.source_provider`. IV is never taken from another provider.
- JSON envelopes of option chains, price history and all three volatility endpoints gain `meta.data_as_of`: the time MDH obtained the data from the provider. It survives cache hits. CSV responses carry it as `X-MDH-Data-As-Of`.
- Response-cache keys of daily-or-longer history requests use the date of `start` and `end`, not the time of day, so a client that sends "now minus N days" no longer creates a new key per request.
- Fail-open: a database outage never fails a market data request; MDH serves from the provider as it does today and retries the database after a cooldown.
- Admin API `GET /api/admin/history-store` (state, series and row counts, newest synchronisation) and `POST /api/admin/history-store/clear` (by dataset, symbol, provider and interval, with confirmation, audit-logged), plus a "History Store" card in the Admin UI.
- `docker-compose.yml` gets a `postgres` service in an optional Compose profile; `doc/deployment.md` and `.env.example` document `DATABASE_URL` and the new settings.

## Capabilities

### New Capabilities
- `market-history-store`: durable PostgreSQL store for closed price bars (`1h`, `4h`, `1d`, `1w`, selectable per provider) and daily IV points, with coverage tracking, incremental synchronisation, revision detection, stale serving on provider failure, fail-open behaviour and admin management.
- `response-data-timestamp`: `meta.data_as_of` on market data responses, preserved across response-cache hits.

### Modified Capabilities
- `response-caching`: daily-or-longer history keys are day-granular; stale responses are never cached.
- `underlying-implied-volatility`: IV Rank and IV Percentile are computed from the stored history when the store is enabled and are served from it when the provider fails.

## Impact

- **Code**: new `app/store/` (engine, models, repositories, synchronisation), Alembic migrations, `app/services/price_service.py`, `app/services/volatility_service.py`, `app/cache.py` (key builder, stale bypass), `app/models/common.py` (typed `meta`), `app/api/routes_prices.py`, `routes_options.py`, `routes_volatility.py`, `routes_admin.py`, `app/main.py` (lifespan), `app/config.py`, `app/admin/provider_config_repository.py` and the provider configuration model (`history_store_intervals`), Admin UI settings page and provider details.
- **Dependencies**: `sqlalchemy[asyncio]`, `asyncpg`, `alembic`.
- **Infrastructure**: PostgreSQL is optional (Compose profile here; for Kubernetes a database outside this repository). Sizing (estimate): 500 symbols with 20 years of daily and weekly bars from two providers and three IV tenors stay below 2 GB including indexes; a 5 Gi volume leaves room for the write-ahead log and reloads. Hourly bars add about 1,750 rows per symbol, provider and year for regular hours and about 4,000 with extended hours; with `1h` stored for 500 symbols a 10 Gi volume is recommended.
- **API**: additive. New `meta` fields; the first and last bar of a daily request are selected by date instead of by timestamp; a stored weekly request starts with the week that contains `start`.
- **Not covered**: intervals below `1h`, monthly bars, intervals a provider does not deliver (`add-derived-price-intervals`), option chains and quotes (they stay in the Redis response cache), scheduled background synchronisation, running credentials and settings in PostgreSQL (a following change: with `DATABASE_URL` set they live in PostgreSQL, without it they stay in SQLite; see design D13), TimescaleDB.
