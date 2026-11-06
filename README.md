<div align="center">

![# Market Data Hub Logo](logo.svg)

# Market Data Hub

</div>


Market Data Hub (MDH) is a focused, production-ready aggregation service for market data. It unifies multiple providers (IBKR, LSEG/Refinitiv, Polygon, Prixe, and Finnhub for news) behind a single, consistent REST/WebSocket API and an MCP server, so your apps can query prices, options, companies, and news without coupling to any one vendor.

**What It Does**
- Aggregates real-time and delayed market data from IBKR, LSEG, Polygon, and Prixe
- Provides options chains and quotes (IBKR), equity prices (IBKR and LSEG), company profiles, and news
- Exposes a clean, provider-agnostic API surface with strong Pydantic models
- Runs reliably in Docker and Kubernetes; supports managed IBKR Gateway

**Why It Exists**
- Broker and data APIs differ wildly; this hub standardizes responses, typing (Decimal for financials), and error handling
- Lets you choose the provider per request (or set sensible defaults) while keeping identical response formats
- Gracefully degrades when certain entitlements are missing (e.g., IBKR Level 2), and documents when behavior differs across providers

**Key Capabilities**
- Prices: latest quotes and historical bars
- Options: chains and quotes with Greeks (IBKR only)
- Companies: profiles, basic search (LSEG)
- News: Finnhub and IBKR; a mock provider is available for development
- [Underlying implied volatility](#underlying-implied-volatility): snapshots, daily history and IV Rank/Percentile (LSEG and IBKR)

**Providers & Data Types**
- IBKR: real-time equities and options; supports `market_data_type` (1=Live/Level 2, 2=Frozen, 3=Delayed)
- LSEG: equity prices via daily summaries; ignores `market_data_type`; not suitable for options Greeks
- Polygon: equity quotes and historical OHLCV (1m-1w granularity)
- Prixe: latest stock price via `POST /api/last_sold` (Bearer token)
- Finnhub: supplemental news and company data for fallback scenarios

**Behavior Highlights**
- `market_data_type` defaults to 3 (Delayed) for IBKR, minimizing subscription requirements
- If you request IBKR Level 1 (Live) without entitlements, the API returns HTTP 503 with a clear error code (`PROVIDER_NOT_AVAILABLE`)
- LSEG returns the latest daily summary and logs an informational message when `market_data_type` is provided (and ignored)
- Historical REST/MCP request dates are normalized to UTC: naive dates mean UTC,
  an omitted end means the current UTC time, and an omitted start means 30 days
  before the effective end. Provider candle timestamps are not rewritten.

**How It Works**
- API Layer (FastAPI) -> Service Layer -> Provider Layer (IBKR/LSEG/Polygon/Prixe/Finnhub)
- Strong Pydantic models ensure type-safety (Decimal for prices, Optional fields for missing data)
- Async-first with `ib_async` for IBKR; synchronous session management for LSEG SDK

**Quick Examples**
- Last price (IBKR, delayed by default):
  - curl "http://localhost:8000/prices/IWM/last?provider=ibkr&market_data_type=3"
- Last price (LSEG, daily summary):
  - curl "http://localhost:8000/prices/IWM/last?provider=lseg"
- Last price (Prixe):
  - curl "http://localhost:8000/prices/IWM/last?provider=prixe"
- Option chain (IBKR only):
  - curl "http://localhost:8000/options/IWM/chain?expiry=2026-01-13&min_strike=227&max_strike=277&market_data_type=3"

See below for setup, configuration, and deployment.

## Quick Start

### Prerequisites
- Python 3.11+
- `uv` for dependency management
- Docker & Docker Compose (optional, for containerized deployment)
- IBKR Gateway/TWS running (for price data)
- Provider credentials stored in `keys.db` via the Admin UI/API (for LSEG, Finnhub, Polygon, Prixe, Schwab)

### Option 1: Local Development (HTTP Mode)

```bash
# 1. Install dependencies
uv sync --frozen --all-extras
uv pip install ruff

# 2. Create runtime .env file
cp .env.example .env
# Provider credentials are added later via Admin UI/API and stored in keys.db.

# 3. Run HTTP server
python -m app.main

# 4. Access Swagger docs
# Open http://localhost:8000/docs
```

### Option 2: Docker Compose (Recommended for Local Dev)

```bash
# 1. Create runtime .env file
cp .env.example .env
# Edit runtime settings as needed. Provider credentials live in keys.db.

# 2. Build and run (builds image automatically)
docker-compose up

# 3. Access Swagger docs
# Open http://localhost:9000/docs

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

When run directly with `python -m app.main`, MDH listens on `APP_PORT` and defaults to `8000`.
The included `.env.example` and Docker Compose setup use `9000` for local containers to avoid collisions with other services.

You can override the port in `.env`:

```bash
APP_PORT=9100
```

### Option 3: Kubernetes Deployment

See [Kubernetes Deployment](#kubernetes-deployment) section below.

## Provider Matrix

**Recommended provider for each data type:**

| Data Type | Primary Provider | Fallback | Reason |
|-----------|-----------------|----------|--------|
| **Stock Prices** | IBKR | LSEG | IBKR provides real-time market data |
| **Historical OHLCV** | IBKR | LSEG, Polygon | Provider coverage depends on symbol and entitlement |
| **Options** | **IBKR ONLY** | - | Other providers lack real-time options Greeks |
| **Company Data** | LSEG | Finnhub | LSEG has comprehensive fundamentals |
| **News** | Finnhub | IBKR | Configure a default in Admin Settings; mock data is available for development |
| **Underlying IV / IV Rank / Percentile** | LSEG or IBKR | - | Provider-specific market/tenor coverage; see [volatility reference](#underlying-implied-volatility) |

LSEG news is no longer exposed by this hub. An explicit `provider=lseg` news
request is rejected as `INVALID_PROVIDER` before any LSEG SDK call. A previously
stored LSEG news default is treated as unconfigured; choose Finnhub, IBKR or mock
in Admin Settings. Other LSEG capabilities are unchanged.

When upgrading a Redis-enabled deployment, clear any pre-existing LSEG news
entries with the confirmed Admin cache-clear operation scoped to
`company_news` and `provider=lseg` (covers HTTP and MCP), rather than flushing
Redis or unrelated provider data. Existing cache entries otherwise retain their TTL.

### ⚠️ LSEG Options Limitation

**LSEG does NOT support options data.** The current LSEG subscription lacks the required `trapi.data.pricing.read` API scope for real-time option pricing and Greeks.

**Attempted workaround (removed):** Previous implementation included Black-Scholes fallback calculations, but these proved unreliable (30-50% error for American options) and production-unsuitable.

**Solution:** Use IBKR exclusively for options data. IBKR provides:
- ✅ Real-time Greeks (Delta, Gamma, Vega, Theta, IV)
- ✅ Server-calculated values (not theoretical models)
- ✅ Support for American options
- ✅ Market microstructure (Bid/Ask spreads, Open Interest)

## Configuration

Runtime configuration via environment variables (see `.env.example`). Provider credentials are stored encrypted in `keys.db` via the Admin UI/API.

**Required for persisted credentials**

| Variable | Default | Description |
|---|---|---|
| `APP_ENCRYPTION_KEY` | *(empty)* | Encryption key for credentials stored in `keys.db`; required before saving credentials |
| `KEYS_DB_PATH` | `./keys.db` | SQLite database path for encrypted provider credentials |

Generate `APP_ENCRYPTION_KEY` with:

```bash
python -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

**Common runtime settings**

| Variable | Default | Description |
|---|---|---|
| `APP_HOST` | `0.0.0.0` | Bind host |
| `APP_PORT` | `8000` | HTTP API, Admin UI, and MCP port |
| `APP_ENV` | `dev` | Environment: `dev`, `test`, or `prod` |
| `LOG_LEVEL` | `INFO` | Logging level |
| `ENABLED_PROVIDERS` | *(empty)* | Optional comma-separated allow-list, e.g. `lseg,ibkr`; empty loads all configured providers |
| `MCP_ENABLED` | `false` | Enables MCP endpoints on the same HTTP port |
| `ADMIN_AUTH_ENABLED` | `true` | Set `false` only for local development |
| `ADMIN_OIDC_ISSUER` | *(empty)* | Required in production when admin auth is enabled |
| `ADMIN_OIDC_CLIENT_ID` | *(empty)* | Required in production when admin auth is enabled |
| `ADMIN_OIDC_CLIENT_SECRET` | *(empty)* | OIDC client secret for admin auth |
| `ADMIN_OIDC_REDIRECT_URI` | *(empty)* | Optional explicit OIDC callback URL |

**Provider runtime settings**

These are operational defaults, not credentials:

| Variable | Default | Description |
|---|---|---|
| `IBKR_HOST` | `127.0.0.1` | Interactive Brokers Gateway/TWS host |
| `IBKR_PORT` | `4001` | Gateway: 4001, TWS Paper: 7497, TWS Live: 7496 |
| `IBKR_CLIENT_ID` | `815` | Unique client ID for connection |
| `IBKR_ACCOUNT_ID` | `DU123456` | Optional account identifier for IBKR operations |
| `IBKR_ENV` | `paper` | `paper` or `live` |
| `IBKR_MARKET_DATA_TYPE` | `3` | 1=Live, 2=Frozen, 3=Delayed, 4=Delayed Frozen |
| `IBKR_CONNECT_ON_REQUEST` | `false` | Lazily connect to IBKR on demand |
| `IBKR_FALLBACK_ON_SUBSCRIPTION_ERROR` | `true` | Handle missing subscriptions gracefully |
| `IBKR_IV_TIMEOUT_SECONDS` | `10` | Maximum wait for a streaming underlying-IV tick; must be positive |
| `LSEG_BASE_URL` | `https://api.lseg.com/v1` | LSEG API base URL |
| `LSEG_RATE_LIMIT_PER_SEC` | `10` | Max LSEG requests per second |
| `LSEG_CACHE_TTL_SECONDS` | `5` | LSEG quote cache TTL; `0` disables cache |
| `LSEG_STRICT_VALIDATION` | `false` | Raise on missing LSEG fields instead of returning partial data |
| `FINNHUB_BASE_URL` | `https://finnhub.io/api/v1` | Finnhub API base URL |
| `FINNHUB_RATE_LIMIT_PER_MIN` | `60` | API rate limit |
| `FINNHUB_FALLBACK_ON_RATE_LIMIT` | `true` | Fallback to mock provider when rate limited |
| `POLYGON_BASE_URL` | `https://api.polygon.io` | Polygon API base URL |
| `PRIXE_BASE_URL` | `https://api.prixe.io` | Prixe API base URL |
| `SCHWAB_CALLBACK_URL` | `http://localhost:8000/api/admin/schwab/callback` | OAuth callback URL; must match the Schwab developer app |
| `SCHWAB_TIMEOUT_SECONDS` | `30` | Schwab request timeout |
| `SCHWAB_RATE_LIMIT_PER_SEC` | `5` | Max Schwab API calls per second |
| `SCHWAB_ASYNCIO` | `true` | Create Schwab async client (`schwab-py` asyncio mode) |
| `SCHWAB_ALERT_WEBHOOK_FORMAT` | `slack` | Alert webhook payload format: `slack`, `generic`, or `discord` |
| `PROVIDER_REQUEST_TIMEOUT` | `10.0` | Default provider request timeout |
| `PROVIDER_MAX_RETRIES` | `3` | Default provider retry count |

**No longer configured via environment variables**

Do not put provider secrets such as `LSEG_APP_KEY`, `LSEG_USERNAME`, `LSEG_PASSWORD`, `FINNHUB_API_KEY`, `POLYGON_API_KEY`, `PRIXE_API_KEY`, `SCHWAB_API_KEY`, `SCHWAB_APP_SECRET`, or `SCHWAB_TOKEN_JSON` in `.env`. Store them in `keys.db` via the Admin UI/API instead.

Provider credential keys:

| Provider | Credential keys in `keys.db` |
|---|---|
| `lseg` | `app_key`, `username`, `password` |
| `finnhub` | `api_key` |
| `polygon` | `api_key` |
| `prixe` | `api_key` |
| `schwab` | `api_key`, `app_secret`, `token_json`, optional `alert_webhook_url` |

## Underlying Implied Volatility

Query the IV of a stock, ETF, index or future without downloading individual
option contracts. This is separate from `/prices/*`: `PriceQuote` is unchanged.
Enable LSEG or IBKR, then choose **Settings → Default Volatility Provider** in
the Admin UI, or pass `provider=lseg|ibkr` on each request. There is no automatic
cross-provider fallback. `/api/admin/providers` exposes each provider's snapshot
security types, history security types and tenors as `volatility_support`.

### Endpoint and unit reference

| Endpoint | Result | Additional parameters |
|---|---|---|
| `GET /volatility/{symbol}` | Snapshot with `implied` tenors 30, 60 and 90 | Common parameters below |
| `GET /volatility/{symbol}/history` | Ascending daily `points` | `start`, `end` (ISO dates); `tenor_days=30|60|90` |
| `GET /volatility/{symbol}/stats` | IV Rank and IV Percentile | `window=20..756` daily points (default 252); `tenor_days=30|60|90` |

Common parameters: `sec_type=stock|etf|index|future` (default `stock`), optional
`provider`, LSEG-only `ric`, and `format=json|csv` (default `json`). History
defaults to **end minus 365 calendar days through today**, with tenor 30.
Both date boundaries are inclusive; `start=end` returns that day's point when
available.
JSON uses the normal `{ "data": ..., "meta": null }` envelope; CSV is an
attachment with one row per tenor/history point, or one row of statistics.

Underlying IV values (`iv_call`, `iv_put`, `iv`, and stats `current`/`min`/`max`)
are **annualized decimal fractions, rounded half-up to four places**. JSON
serializes them as strings: `"0.2676"` means **26.76%**. Multiply by 100 for
display; use fractions directly in volatility/variance formulas. IV may exceed
1 (100%). All three snapshot tenors are always present in order; unavailable
tenors are null. `iv` is the mean of available call/put values, or a provider's
combined value. IBKR supplies only combined 30-day `iv`, with null call/put.

**Breaking change for Schwab option consumers:** per-contract
`OptionQuote.implied_volatility` is now a fraction too (`22.345` upstream →
`0.22345`), consistent with IBKR and Polygon. Per-contract precision is retained;
the four-place rule above is for underlying IV. Missing/NaN values and negative
Schwab sentinels such as `-999` return null.

### Verified provider coverage

| Provider | Snapshot security types | History / stats security types | Tenors | `method` |
|---|---|---|---|---|
| LSEG | stock, ETF, index, future | stock, ETF, index, future | 30, 60, 90 | `provider_atm_index` |
| IBKR | stock, ETF, index, future | stock, ETF, index only | 30 | `provider_model_30d` |

- **LSEG:** constant-maturity ATM indices via streaming FIDs, not REST pricing
  snapshots or `TR.*` datagrid fields (those scopes are not entitled).
  Stock/ETF/index records use `{SYMBOL}ATMIV.U`, where `.U` means **OPRA**.
  Futures use `{ROOT}ATMIV` without `.U`; verified roots include ES, NQ, YM,
  C (corn), W (wheat) and TY (10-year Treasury). Futures roots differ by provider:
  IBKR uses ZC, ZW and ZN for those last three markets.
- LSEG returns `underlying`, `underlying_name`, `market` and `as_of`. Values are
  end-of-day for most stock/ETF records; index values can update roughly hourly.
  Automatic RIC resolution requires `OPRA` for stock/ETF/index and
  `COMFUT`/`CMEG` for futures. `ESATMIV.U` is **Eversource**, and `CLATMIV.U` is
  **Colgate**, not futures. Set `sec_type` explicitly; a wrong market is rejected.
  A supplied `ric` is queried verbatim and skips this market check, enabling
  Eurex records such as `GDAXATMIV.EX`, `STXEATMIV.EX` and `SAPGATMIV.EX`.
- **IBKR:** streaming generic tick 106 supplies a live/delayed 30-day model.
  Live-subscription refusal retries once with delayed data when fallback is
  enabled. Futures use the nearest contract with at least seven days to last
  trade. The front-month `localSymbol` (e.g. `CLZ6`) is returned as
  `source_instrument`. Daily history uses `OPTION_IMPLIED_VOLATILITY`; futures
  history is rejected because the upstream series is unusable, not interpolated.
  `ric` is rejected. RUT uses RUSSELL, NDX NASDAQ, and SPX/VIX CBOE.
- **Gaps:** LSEG lacks energy/metals futures IV; IBKR covers CL/NG snapshots,
  but not metals futures IV. Use ETF proxies **USO, UNG, GLD, SLV** for available
  history, remembering that an ETF's IV is not the future's IV. LSEG ES/NQ ATMIV
  can sit materially below cash-index IV; prefer `sec_type=index` with SPX/NDX
  for equity-index exposure. Provider values/methods are not interchangeable.
- **Polygon is not an underlying-IV provider:** our plan denies option snapshots
  (403, verified 2026-11-06), and Polygon offers no underlying IV history.
  Schwab exposes per-contract IV, not underlying IV.

### How to fetch IV and its daily history

With an enabled, credentialed provider (or a running IBKR Gateway/TWS), run:

```bash
curl 'http://localhost:9000/volatility/AAPL?provider=lseg'
curl 'http://localhost:9000/volatility/SPY?sec_type=etf&provider=lseg'
curl 'http://localhost:9000/volatility/SPX?sec_type=index&provider=lseg'
curl 'http://localhost:9000/volatility/ES?sec_type=future&provider=lseg'
curl 'http://localhost:9000/volatility/CL?sec_type=future&provider=ibkr'
curl 'http://localhost:9000/volatility/DAX?sec_type=index&ric=GDAXATMIV.EX&provider=lseg'
curl 'http://localhost:9000/volatility/AAPL/history?provider=lseg&tenor_days=30&format=csv'
```

Verify `provider`, `source_instrument`, `market`, `as_of` and the three tenors.
HTTP 400 means the provider is not a volatility provider; 422 means invalid
input/market or IBKR `ric`; 501 means an unsupported operation/tenor (e.g. IBKR
futures history or 60-day history); 404 means no usable data; 503 means provider
connectivity, timeout, configuration or entitlement failure. An unset default
also returns 503 unless an explicit provider is supplied.

### How to request IV Rank and IV Percentile

```bash
curl 'http://localhost:9000/volatility/AAPL/stats?provider=lseg&window=252'
curl 'http://localhost:9000/volatility/SPX/stats?sec_type=index&provider=ibkr&format=csv'
```

Stats uses the last `window` usable daily points from **one provider**, including
the latest available point as `current`. `window_points` reports the number
actually available (at most `window`); fewer than 20 returns 404
`insufficient_history`. `window_start`/`window_end` are the actual point dates.

- **IV Rank (IVR)** = `(current − min) / (max − min) × 100`; null when the window
  is flat. It is sensitive to a single outlier day because it uses min/max.
- **IV Percentile (IVP)** = the share of **prior points strictly below current**
  × 100, excluding current from the denominator. Ties are not counted as below.
  It is more resistant to isolated outliers; a flat window has IVP 0.
- Both ranks are **0–100 with two decimal places**, not fractional IV. There is
  **no outlier filter** in this version. IBKR history can contain bad daily prints.

MCP exposes `get_implied_volatility`, `get_implied_volatility_history` and
`get_implied_volatility_stats` with the same units/support. All accept `symbol`,
`sec_type`, `ric`, `provider` and `refresh`; history uses `start_date`/`end_date`
instead of HTTP `start`/`end`; history/stats accept `tenor_days`, and stats accepts
`window`. For example:

```json
{"name":"get_implied_volatility_stats","arguments":{"symbol":"SPY","sec_type":"etf","provider":"lseg","window":252,"refresh":true}}
```

See [Redis Response Cache](#redis-response-cache) for TTLs, refresh and clear scopes.

## Redis Response Cache

`GET /options/{symbol}/chain`, `GET /prices/{symbol}/history`, company profiles,
company search, company news (JSON/CSV), `GET /market-status` and all three
`/volatility/*` endpoints cache responses in Redis, for every provider.
Their nine MCP counterparts use the same backend
and TTL policy with separate entries; `refresh: true` fetches live and overwrites
the MCP entry. Redis is optional: outages serve live provider data, log one
warning, and retry after a 30-second cooldown. Requests without application
startup, and deployments with `CACHE_ENABLED=false`, do not access Redis.

Never cached: `/prices/{symbol}/last`, `/options/{symbol}/quote/{option_id}`,
`/health`, `/metrics`, `/providers`, `/api/admin/*`, WebSockets, and the MCP tools
`get_last_price` / `get_option_quote`.

Docker Compose includes Redis 7 Alpine on the internal network only (no host
port), with `redis-data:/data` persistence, RDB snapshots (`300 1`, `60 1000`),
no AOF, and `allkeys-lru` eviction. MDH starts even if Redis is unhealthy.
Graceful `docker compose down` preserves the volume and saves a snapshot;
`docker compose up -d` restores unexpired entries. A crash can lose up to about
five minutes of recent entries. Do not use `down -v` if you want to preserve
the cache **or the existing keys database**.

| Variable | Default | Meaning |
| --- | --- | --- |
| `CACHE_ENABLED` | `true` | Enable response caching |
| `REDIS_URL` | `redis://localhost:6379/0` | Standalone Redis URL; Compose defaults to `redis://redis:6379/0` |
| `REDIS_TIMEOUT_SECONDS` | `1.0` | Connect and socket timeout per Redis call |
| `CACHE_TTL_OPTION_CHAIN_SECONDS` | `900` | Option-chain session TTL |
| `CACHE_TTL_HISTORICAL_CLOSED_SECONDS` | `604800` | Closed historical ranges (7 days); cap for closed-market extension |
| `CACHE_TTL_HISTORICAL_OPEN_BAR_SECONDS` | `300` | Forming daily/weekly/monthly bars |
| `CACHE_TTL_HISTORICAL_INTRADAY_SECONDS` | `300` | Intraday bars; capped at bar length (`1m` → 60 s) |
| `CACHE_TTL_COMPANY_PROFILE_SECONDS` | `86400` | Company profiles (24 hours) |
| `CACHE_TTL_COMPANY_SEARCH_SECONDS` | `3600` | Company search (1 hour) |
| `CACHE_TTL_COMPANY_NEWS_SECONDS` | `600` | Company news (10 minutes) |
| `CACHE_TTL_MARKET_STATUS_SECONDS` | `60` | Market status; capped at the next weekday 04:00/09:30/16:00/20:00 ET transition |
| `CACHE_TTL_VOLATILITY_SECONDS` | `900` | IV snapshot, stats and open-range IV history; never extended overnight |
| `CACHE_EXTEND_WHEN_MARKET_CLOSED` | `true` | Keep open ranges/chains until next US market open |
| `REDIS_MAXMEMORY` | `256mb` | Compose Redis memory bound |

These TTLs are initial defaults. **Admin UI → Settings → Response Cache** shows
connection state, redacted Redis URL, memory, key counts and market state. Its
policy form saves overrides to `system_settings` in `keys.db` without restarting
or requiring Redis. TTLs accept 0–2592000 seconds (30 days); 0 disables writes
for that policy, including its closed-market extension. Other replicas sharing
`keys.db` pick up changes within 30 seconds. Existing entries retain their TTL;
use **Clear cache…** for immediate invalidation, optionally scoped to an endpoint
and/or provider. Clearing requires acknowledgement because following requests
hit broker APIs live and can trigger rate limits.

The TTL policy uses US equity sessions in `America/New_York`: Mon–Fri
09:30–16:00, or 04:00–20:00 for `extended_hours=true`, with 30 minutes of settle
grace after close. Settled-market entries last until the next open, capped by
the closed-range TTL. Holidays count as weekdays (extra refreshes, not extra
staleness). The extension applies only to option chains and historical prices,
never to company data, market status or implied volatility. **Disable the extension for non-US symbols.**

Volatility snapshots and stats always use `volatility_seconds` (default 900 s).
Volatility history uses the same closed daily-range cutoff (explicit `end`
strictly before yesterday 00:00 ET) and `historical_closed_seconds` (7 days);
otherwise it uses `volatility_seconds`. Date-only IV `end` values mean midnight
ET. The market-closed extension does not apply: daily IV is published **after**
the close, so extending a pre-update value until the next open would hide it.
Setting `volatility_seconds=0` disables snapshot/stats/open-history caching,
while closed history still uses its own TTL.

An explicit historical `end` uses the closed-range TTL only if safely before
the current period: intraday before today midnight ET, daily before yesterday
midnight ET, weekly before this Monday minus one day, monthly before this
month's first day minus one day. Naive `end` timestamps mean UTC. `1m` means
minute; `1mo` means month. Ranges containing a forming bar use the short TTL,
including during settle grace. Long-lived closed ranges can miss subsequent
split/dividend adjustments; clear their cache after corporate actions.

Keys are transparent: `mdh:{route_path}:{SYMBOL}:{sorted_urlencoded_query}`,
e.g. `mdh:options:chain:SPX:provider=schwab`. Only declared non-empty query
parameters contribute; symbol is uppercased, `provider`/`format`/`sec_type`
lowercased. The effective provider (explicit or registry default) is part of
the key, so changing a default provider cannot serve another provider's data.
ISO datetime colons are URL-encoded. Entries are not automatically invalidated
when provider configuration or response schemas change; clear affected entries
after such changes. Concurrent misses can still call the provider concurrently.

Company route keys are `companies:profile`, `companies:search`, and
`companies:news`; search and market-status keys have an empty symbol segment.
Search queries are trimmed, whitespace-collapsed and lowercased in the key only.
Volatility keys are `volatility:snapshot`, `volatility:history` and
`volatility:stats`; `ric`, `tenor_days` and `window` isolate their entries.
Default providers are resolved per capability (company, news, options, price or
volatility via `default_volatility_provider`). The `volatility` clear scope and
key count cover all three operations in both channels.
MCP keys add `channel=mcp` and use HTTP parameter names (`start`, `end`, `q`, etc.);
HTTP ignores undeclared parameters, including `channel`. Admin key counts and
endpoint/provider clear scopes include both channels.

Cached responses include `X-FastAPI-Cache: HIT|MISS`, `ETag`, and `Cache-Control`
with the effective write TTL on MISS or remaining TTL on HIT. TTL 0 returns
`Cache-Control: no-store`. `If-None-Match` supports 304 revalidation.

```bash
# Force a live fetch and refresh the cache entry:
curl -H 'Cache-Control: no-cache' 'http://localhost:9000/options/SPX/chain?provider=schwab'
curl -H 'Cache-Control: no-cache' 'http://localhost:9000/volatility/AAPL?provider=lseg'
# Fetch live without reading or writing the cache:
curl -H 'Cache-Control: no-store' 'http://localhost:9000/prices/AAPL/history?provider=schwab'
# Admin API (requires an admin token when admin authentication is enabled):
curl -H "Authorization: Bearer $ADMIN_TOKEN" http://localhost:9000/api/admin/cache
curl -X PUT -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"historical_intraday_seconds":120}' http://localhost:9000/api/admin/cache/policy
curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"confirm":true,"scope":"options_chain","provider":"schwab"}' \
  http://localhost:9000/api/admin/cache/clear
```

Clearing uses non-blocking `SCAN` + batched `UNLINK`, never `KEYS` or `FLUSHDB`,
and leaves foreign Redis keys untouched. Policy changes and clears are audited.

### Isolated Compose verification (no broker access)

The verification overlay replaces market services with deterministic fakes but
uses the real application lifespan, routes and Redis. It disables admin auth,
uses a public test encryption key, ignores `.env` credentials, and runs under a
separate project name/port. **Never use this overlay in production.**

```bash
APP_PORT=19090 docker compose -p mdh-cache-verification -f docker-compose.yml \
  -f tests/compose/cache_override.yaml up --build -d
curl -i 'http://localhost:19090/options/AAPL/chain?provider=schwab' # MISS then HIT
python tests/compose/cache_probe.py warm # JSON + CSV for both routes: MISS then HIT
python tests/compose/cache_probe.py coverage # all six cached capabilities, HTTP + MCP
APP_PORT=19090 docker compose -p mdh-cache-verification -f docker-compose.yml \
  -f tests/compose/cache_override.yaml exec -T redis redis-cli --scan --pattern 'mdh:*'
APP_PORT=19090 docker compose -p mdh-cache-verification -f docker-compose.yml \
  -f tests/compose/cache_override.yaml stop redis
curl -i 'http://localhost:19090/options/AAPL/chain?provider=schwab' # live HTTP 200
python tests/compose/cache_probe.py outage # all four responses live; Redis unavailable
# down (without -v) then up verifies unexpired entries still HIT.
APP_PORT=19090 docker compose -p mdh-cache-verification -f docker-compose.yml \
  -f tests/compose/cache_override.yaml down
# Bring up the same isolated project, then verify restored entries:
APP_PORT=19090 docker compose -p mdh-cache-verification -f docker-compose.yml \
  -f tests/compose/cache_override.yaml up -d
python tests/compose/cache_probe.py persisted
# Stop the verification stack afterward with the same down command (without -v).
```

## Observability

MDH exposes Prometheus-compatible request metrics at `GET /metrics` and emits one structured JSON audit log line for each completed API request. Health, metrics, docs, OpenAPI, and admin endpoints are skipped for audit logs.

Metrics use bounded labels only: `provider`, `endpoint`, and `status_class`. Ticker symbols, client IDs, and query parameters are never used as metric labels.

Example Prometheus scrape config:

```yaml
scrape_configs:
  - job_name: market-data-hub
    metrics_path: /metrics
    static_configs:
      - targets:
          - localhost:9000
```

Audit logs are written to stdout as JSON lines with `event="request_completed"` and fields such as `client_id`, `method`, `path`, `provider`, `params`, `status_code`, and `duration_ms`. Set `X-Client-ID` on requests to identify clients; otherwise logs use `anonymous`.

### LSEG Credentials Setup

To access Refinitiv/LSEG data, obtain credentials from [LSEG Developer Portal](https://developer.lseg.com/):

1. Create or sign in to your LSEG account
2. Generate API key in Developer Portal
3. Note your LSEG Workspace username (typically email address)
4. Store credentials in `keys.db` via Admin UI/API under provider `lseg` with keys `app_key`, `username`, and `password`.

**Note**: Data access requires active LSEG subscription with appropriate entitlements for the data types you retrieve.

### Finnhub Credentials Setup

To access company news and data from Finnhub (fallback provider), obtain an API key from [Finnhub.io](https://finnhub.io/):

1. Sign up for a free account at [finnhub.io/register](https://finnhub.io/register)
2. Get your API key from the [Dashboard](https://finnhub.io/dashboard)
3. Store the API key in `keys.db` via Admin UI/API under provider `finnhub` with key `api_key`.

**Rate Limits**:
- Free tier: 60 API calls per minute
- Premium: 300-600 calls/min depending on plan
- Rate limit handling: Automatically falls back to mock provider when limit exceeded (configurable via `FINNHUB_FALLBACK_ON_RATE_LIMIT`)

See [doc/news-api-guide.md](doc/news-api-guide.md) for detailed news API usage and testing.

### Schwab Credentials Setup

Schwab requires OAuth2 authentication via the [Schwab Developer Portal](https://developer.schwab.com/). The `schwab-py` library manages the token lifecycle automatically once set up.

#### 1. Create a Schwab developer app

1. Sign in at [developer.schwab.com](https://developer.schwab.com/)
2. Create a new app under **Products → Trader API – Individual**
3. Set the callback URL to `https://127.0.0.1:8182` (or another `https://127.0.0.1:<port>` URL)
4. Note your **App Key** and **App Secret**

> **App approval delay:** New and modified apps enter an `Approved - Pending` state and require manual review by Schwab. This typically takes a few days. Until the status shows **Ready for Use**, API calls will return `401` errors.

#### 2. Generate the token (one-time per machine)

Run the token generator on a machine with a browser:

```bash
schwab-generate-token.py \
  --token_file /path/to/_token.json \
  --api_key YOUR_APP_KEY \
  --app_secret YOUR_APP_SECRET \
  --callback_url https://127.0.0.1:8182
```

A browser window will open. Log in with your Schwab brokerage account. After redirecting, the token file is written automatically.

> Your browser will warn about an invalid/self-signed certificate on the callback URL — this is expected. Proceed anyway, but verify the address matches your callback URL.

#### 3. Store credentials in `keys.db`

Store credentials via Admin UI/API under provider `schwab`:

| Credential key | Value |
|---|---|
| `api_key` | App key from the developer portal |
| `app_secret` | App secret from the developer portal |
| `token_json` | Full contents of the generated `_token.json` file |
| `alert_webhook_url` | Optional alert webhook URL |

Keep `SCHWAB_CALLBACK_URL` in `.env`; it is runtime configuration and must match the developer portal app exactly.

#### 4. Token rotation (every 7 days)

Schwab refresh tokens expire after **7 days**. Re-run `schwab-generate-token.py` weekly before the token expires, or set a cron job:

```bash
# Example: regenerate token every Sunday at 08:00
0 8 * * 0 schwab-generate-token.py --token_file /path/to/token.json --api_key YOUR_APP_KEY --app_secret YOUR_APP_SECRET --callback_url https://127.0.0.1:8182
```

#### 5. Containerized / headless deployments

The login flow requires a browser. For servers:

1. Generate the token on a local machine (step 2 above)
2. Copy `_token.json` to the server / mount it as a secret
3. **Never share or commit the token file** — it grants full account access

**Do not** create, edit, or copy-paste the JSON contents manually. The token file is managed exclusively by `schwab-py`.

#### Verify the setup

```bash
# Check provider is active (requires running server)
curl http://localhost:8000/providers | python -m json.tool

# Fetch historical daily prices via 
curl "http://localhost:8000/prices/history/AAPL?interval=1d&period=1y&provider="
```

## Admin UI

Market Data Hub includes a web-based Admin UI for managing providers, credentials, and monitoring system status.

### Accessing the Admin UI
- **URL:** `http://localhost:9000/admin`
- **Dashboard:** Real-time provider status and configuration summary.
- **Provider Management:** Enable/disable providers and hot-reload runtime configuration (timeout, retries, rate limits, circuit breakers).
- **Credential Management:** Securely update API keys and secrets (stored encrypted in SQLite).
- **Schwab Authorization:** Guided step-by-step workflow for the 7-day manual OAuth2 re-authorization.
- **Alerts:** Configure Slack/JSON webhooks for system notifications.

### Local Development Setup (Frontend)
The Admin UI is built with React, TypeScript, and Vite.

```bash
cd admin
npm install
npm run dev
```

The Vite dev server proxies `/api` requests to the FastAPI backend on port 8000.

### Docker Compose UI Hot Reload (without `--build`)

If you run backend via Docker Compose and want `/admin` to update after UI edits without rebuilding the image each time:

```bash
# Terminal 1: build UI continuously to admin/dist
cd admin
npm run build:watch

# Terminal 2: run backend container once
cd ..
docker compose up
```

`docker-compose.yml` binds `./admin/dist` to `/app/static/admin`, so refreshing `http://localhost:9000/admin` picks up new UI assets directly.

For a one-shot UI refresh trigger (instead of watch mode):

```bash
cd admin && npm run build
```

No `docker compose up --build` required for UI-only changes.

## Running Modes

```bash
# HTTP REST API + optional MCP (single process, default port 8000)
python -m app.main

# With MCP enabled (exposes MCP on the same HTTP port)
MCP_ENABLED=true python -m app.main

# Docker Compose
docker-compose up

# Docker with MCP enabled
docker run -p 8000:8000 \
  --env-file .env \
  -e MCP_ENABLED=true \
  market-data-hub:latest
```

### MCP Integration

When `MCP_ENABLED=true`, the MCP (Model Context Protocol) endpoints are available at:

| Endpoint | Description |
|----------|-------------|
| `GET  /mcp` | SSE stream alias for clients configured with the base MCP URL |
| `POST /mcp` | Streamable HTTP JSON-RPC calls for remote MCP clients such as Claude |
| `GET  /mcp/sse` | SSE stream — establishes a session and receives tool results |
| `POST /mcp/messages?session_id=<id>` | JSON-RPC 2.0 tool calls |

For Claude remote MCP, configure `http://localhost:8000/mcp` or the deployed equivalent. Legacy SSE clients can use `http://localhost:8000/mcp/sse`.

Available MCP tools: `get_last_price`, `get_historical_prices`, `get_option_chain`, `get_option_quote`, `get_company_profile`, `search_companies`, `get_company_news`, `get_market_status`, `get_implied_volatility`, `get_implied_volatility_history`, `get_implied_volatility_stats`. See the [volatility reference](#underlying-implied-volatility) for the new tools' units, inputs and provider limits.

For more details on connecting clients and using the tools, see the [MCP Guide](doc/mcp-guide.md).

## Architecture

This service implements the **Aggregator Pattern**:
- **API Layer**: Exposes unified REST and WebSocket endpoints.
- **Service Layer**: Orchestrates data fetching and business logic.
- **Provider Layer**: Abstracts external APIs (IBKR, LSEG) via strict interfaces.

## API Examples

### Health Check
```bash
curl http://localhost:8000/health
```

### Get Last Price
```bash
curl "http://localhost:8000/prices/AAPL/last?provider=ibkr&market_data_type=3"
```

Provider behavior for `/prices/{symbol}/last`:
- IBKR: honors `market_data_type` (1=Live, 2=Frozen, 3=Delayed). Level 1 requires subscription; if unavailable, returns HTTP 503.
- LSEG: ignores `market_data_type` and returns the latest daily summary via Refinitiv `historical_pricing.summaries`.

### Get Company Profile
```bash
curl "http://localhost:8000/companies/AAPL?provider=lseg"
```

### WebSocket Prices
Connect to `ws://localhost:8000/ws/prices` and send:
```json
{"type": "subscribe", "symbols": ["AAPL"], "provider": "ibkr"}
```

## Kubernetes Deployment

### Prerequisites
- kubectl configured with cluster access
- Kubernetes 1.19+
- IBKR Gateway accessible from cluster

### Setup Steps

```bash
# 1. Create namespace
kubectl create namespace market-data-hub

# 2. Create Kubernetes Secret for admin runtime storage
kubectl create secret generic market-data-hub-secrets \
  --from-literal=app_encryption_key=$APP_ENCRYPTION_KEY \
  -n market-data-hub

# Provider credentials are stored in keys.db; seed them through the Admin UI/API
# after deployment, or mount/persist KEYS_DB_PATH with preloaded credentials.

# 3. Update image reference in deploy/kubernetes.yaml
# Replace: ghcr.io/yourusername/market-data-hub:latest
sed -i 's|ghcr.io/yourusername/market-data-hub:latest|ghcr.io/YOUR_USERNAME/market-data-hub:latest|g' deploy/kubernetes.yaml

# 4. Apply Kubernetes resources (all-in-one file)
kubectl apply -f deploy/kubernetes.yaml -n market-data-hub

# 5. Verify deployment
kubectl get pods -n market-data-hub
kubectl logs -n market-data-hub deployment/market-data-hub

# 6. Port forward for local testing
kubectl port-forward -n market-data-hub svc/market-data-hub 8000:8000 &
curl http://localhost:8000/health
```

### Update Deployment

```bash
# Update with new image
kubectl set image deployment/market-data-hub \
  app=ghcr.io/username/market-data-hub:v1.0.0 \
  -n market-data-hub

# Watch rollout
kubectl rollout status deployment/market-data-hub -n market-data-hub

# Rollback if needed
kubectl rollout undo deployment/market-data-hub -n market-data-hub
```

### Cleanup

```bash
# Remove all resources
kubectl delete -f deploy/kubernetes.yaml -n market-data-hub
kubectl delete namespace market-data-hub
```

## Docker Image Building & Pushing

### Local Build
```bash
docker build -t market-data-hub:latest .
```

### Push to GitHub Container Registry (GHCR)
```bash
# Automatic via GitHub Actions on push to main/develop or tag creation
# Images pushed to: ghcr.io/yourusername/market-data-hub:latest

# Or manual push:
docker login ghcr.io -u USERNAME -p TOKEN
docker tag market-data-hub:latest ghcr.io/yourusername/market-data-hub:latest
docker push ghcr.io/yourusername/market-data-hub:latest
```

### Docker Compose Auto-Build
The `docker-compose.yml` automatically builds the image locally:
```bash
docker-compose up --build  # Force rebuild
docker-compose up          # Use cache if available
```

## Deployment Files

All deployment resources are in the `deploy/` directory:

| File | Purpose |
|---|---|
| `kubernetes.yaml` | Combined K8s ConfigMap, Deployment, Service manifest |
| `secret-template.yaml` | Template showing Secret structure (never commit with real values) |
| `.env.example` | Environment variables template |

See [doc/deployment.md](doc/deployment.md) for detailed deployment documentation.

## Development

### Running Tests
```bash
uv run pytest --maxfail=1 --disable-warnings
```

### Code Linting
```bash
uv run ruff check app/
python skills/lint_check.py --all
```

### API Documentation
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
