<div align="center">

![# Market Data Hub Logo](logo.svg)

# Market Data Hub

</div>

Market Data Hub (MDH) aggregates market data providers (IBKR, LSEG, Schwab, Polygon, Prixe, Finnhub) behind one REST/WebSocket API and an MCP server. Responses are provider-agnostic Pydantic models (`Decimal` for all financial values).

**Capabilities:** latest prices and historical bars · option chains/quotes with Greeks · company profiles/search · news · underlying implied volatility (IV, IV Rank/Percentile) · Redis response cache · Admin UI · Prometheus metrics.

```
FastAPI (app/api) → services → provider registry → IBKR (async) | LSEG (sync SDK) | Schwab | Polygon | Prixe | Finnhub
MCP is mounted in the same FastAPI app (same port)
```

## Providers

| Data | Primary | Fallback | Notes |
|---|---|---|---|
| Prices (stock, ETF, index, future) | IBKR | LSEG, Polygon, Prixe, Schwab | IBKR honors `market_data_type` (1 Live, 2 Frozen, 3 Delayed; default 3). Missing subscription → HTTP 403 `PROVIDER_NOT_ENTITLED`. See [Symbol notation](#symbol-notation). |
| Historical OHLCV | IBKR | LSEG, Polygon, Schwab | Coverage depends on symbol/entitlement. Schwab has no futures history. |
| Options (chain, quote, Greeks) | IBKR | Schwab | Not available via LSEG (missing pricing scope in our subscription). |
| Company data | LSEG | Finnhub | |
| News | Finnhub | IBKR | LSEG news is not exposed (`provider=lseg` → `INVALID_PROVIDER`). Mock provider for development. |
| Underlying IV | LSEG, IBKR | – | See [Implied Volatility](#underlying-implied-volatility). Polygon/Schwab are not underlying-IV providers. |

Historical REST/MCP dates are normalized to UTC: naive means UTC, omitted `end` = now, omitted `start` = `end` − 30 days.

## Symbol notation

Every REST route, MCP tool and WebSocket subscription takes the same symbol notation `[<NS>:]<ROOT>` (case-insensitive, whitespace ignored):

| Input | Meaning | Canonical |
|---|---|---|
| `AAPL`, `SPY` | Stock or ETF (bare symbol) | `AAPL`, `SPY` |
| `I:SPX`, `^SPX` | Index | `I:SPX` |
| `F:ES`, `/ES` | Future (front month) | `F:ES` |
| `O:AAPL250117C00150000` | Option contract (OCC symbol, option ids only) | – |

- A bare symbol is always a stock/ETF: bare `SPX` or `NDX` is **not** an index. Use `I:SPX`, `^SPX` or `sec_type=index`.
- `/ES` works wherever the symbol is not a URL path segment (MCP arguments, WebSocket, query parameters). In REST paths use `F:ES`; `^SPX` may need `%5E` in strict clients.
- `sec_type` (`stock|etf|index|future|option`, case-insensitive, legacy `STK`) stays valid. It must agree with a prefix (`F:ES?sec_type=stock` → 422); `ES?sec_type=future` equals `F:ES`; `sec_type=etf` only combines with bare symbols.
- Provider-native forms (`.SPX`, `$SPX`) are rejected with 422 and a suggestion (`I:SPX`). Native identifiers stay reachable through override parameters such as `ric`.
- Responses echo the canonical symbol (`symbol`, `underlying_symbol`). `source_instrument` on prices shows the native instrument actually queried (`ESZ6`, `ESc1`, `.SPX`, `$SPX`).
- Futures mean the front month: last price uses the nearest contract, history the provider's continuous series (IBKR `ContFuture`, LSEG `c1`), without back-adjustment.

Supported types per endpoint: prices and volatility `stock|etf|index|future`; option chain/quote underlying `stock|etf|index`; company profile/news `stock|etf`; WebSocket `stock|etf|index|future`. Anything else → 422 before a provider is called.

| Type | IBKR | LSEG | Schwab | Polygon | Prixe |
|---|---|---|---|---|---|
| stock/ETF | `Stock(SMART)` | equity RIC search | `AAPL` | `AAPL` | `AAPL` |
| index | `Index` (`DJI`→`INDU`) | `.SPX` | `$SPX` | `I:SPX` | – |
| future | front-month `Future` / `ContFuture` | `ESc1` (`ZN`→`TY`, `ZB`→`US`, `ZC`→`C`, `ZW`→`W`, `ZS`→`S`) | `/ES` (quotes only) | – | – |
| index option underlying | – | – | `$SPX` | `I:SPX` | – |

Error semantics: **501** `CAPABILITY_NOT_SUPPORTED` means the hub has no mapping for this type at that provider (decided from code, before any call). **403** `PROVIDER_NOT_ENTITLED` means the provider denied access because your subscription does not cover the instrument (decided from the provider's response at request time, never cached; `details` carry `provider`, `symbol`, `instrument`, `provider_message`). 401/credential failures stay `PROVIDER_NOT_AVAILABLE`. Admin → provider details lists the declared support sets.

**Breaking changes:** `symbol` in responses is canonical (`I:SPX`, `F:ES` instead of `SPX`, `ES`; stocks unchanged) · missing subscriptions answer 403 `PROVIDER_NOT_ENTITLED` instead of 503 · `.SPX`/`$SPX` input is rejected · index/future requests at providers without a mapping answer 501 instead of returning stock-like data · cache keys changed (old entries expire; optionally clear the cache).

## Quick Start

Requires Python 3.11+, [`uv`](https://docs.astral.sh/uv/), and optionally Docker and a running IBKR Gateway/TWS.

```bash
uv sync --frozen --all-extras
cp .env.example .env            # runtime settings only; credentials go to keys.db
python -m app.main              # http://localhost:8000/docs
```

Docker Compose (includes Redis; `.env.example` uses port 9000):

```bash
cp .env.example .env
docker compose up               # http://localhost:9000/docs
```

Compose builds the image locally by default and tags it `ghcr.io/framatsch/market-data-hub:latest`. To use the published image instead: `docker compose pull && docker compose up --no-build` (override with `MDH_IMAGE`).

Examples:

```bash
curl "http://localhost:8000/health"
curl "http://localhost:8000/prices/IWM/last?provider=ibkr&market_data_type=3"
curl "http://localhost:8000/options/IWM/chain?expiry=2026-01-13&min_strike=227&max_strike=277"
curl "http://localhost:8000/companies/AAPL?provider=lseg"
curl "http://localhost:8000/prices/I:SPX/last?provider=ibkr"
curl "http://localhost:8000/prices/F:ES/history?provider=lseg&interval=1d"
```

WebSocket: connect to `ws://localhost:8000/ws/prices` and send `{"type":"subscribe","symbols":["AAPL"],"provider":"ibkr"}`.

## Configuration

Settings come from environment variables (see `.env.example`). **Provider credentials are never read from env vars**; store them encrypted in `keys.db` via the Admin UI/API.

| Variable | Default | Description |
|---|---|---|
| `APP_ENCRYPTION_KEY` | – | Required to save credentials in `keys.db` |
| `KEYS_DB_PATH` | `./keys.db` | Encrypted credentials DB |
| `APP_HOST` / `APP_PORT` | `0.0.0.0` / `8000` | Bind address (HTTP, Admin, MCP share the port) |
| `APP_ENV` | `dev` | `dev`, `test`, `prod` (`prod` requires admin OIDC) |
| `LOG_LEVEL` | `INFO` | |
| `ENABLED_PROVIDERS` | all | Allow-list, e.g. `lseg,ibkr` |
| `MCP_ENABLED` | `false` | Enable MCP endpoints |
| `ADMIN_AUTH_ENABLED` | `true` | Disable only locally |
| `ADMIN_OIDC_ISSUER`, `ADMIN_OIDC_CLIENT_ID`, `ADMIN_OIDC_CLIENT_SECRET`, `ADMIN_OIDC_REDIRECT_URI` | – | Admin OIDC login |
| `IBKR_HOST` / `IBKR_PORT` | `127.0.0.1` / `4001` | Gateway 4001, TWS paper 7497, TWS live 7496 |
| `IBKR_CLIENT_ID`, `IBKR_ACCOUNT_ID`, `IBKR_ENV` | `815`, – , `paper` | |
| `IBKR_MARKET_DATA_TYPE` | `3` | 1 Live, 2 Frozen, 3 Delayed, 4 Delayed Frozen |
| `IBKR_CONNECT_ON_REQUEST` | `false` | Connect lazily |
| `IBKR_FALLBACK_ON_SUBSCRIPTION_ERROR` | `true` | Degrade gracefully on missing entitlements |
| `IBKR_IV_TIMEOUT_SECONDS` | `10` | Wait for streaming IV tick |
| `LSEG_RATE_LIMIT_PER_SEC`, `LSEG_CACHE_TTL_SECONDS`, `LSEG_STRICT_VALIDATION` | `10`, `5`, `false` | |
| `FINNHUB_RATE_LIMIT_PER_MIN`, `FINNHUB_FALLBACK_ON_RATE_LIMIT` | `60`, `true` | Falls back to mock when rate limited |
| `SCHWAB_CALLBACK_URL` | `http://localhost:8000/api/admin/schwab/callback` | Must match the Schwab app |
| `PROVIDER_REQUEST_TIMEOUT` / `PROVIDER_MAX_RETRIES` | `10.0` / `3` | |

Further provider base-URL/Schwab tuning variables are listed in `.env.example`.

Generate an encryption key:

```bash
python -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

### Provider credentials (`keys.db`)

| Provider | Keys | Where to get them |
|---|---|---|
| `lseg` | `app_key`, `username`, `password` | [LSEG Developer Portal](https://developer.lseg.com/); entitlements depend on your subscription |
| `finnhub` | `api_key` | [finnhub.io](https://finnhub.io/) (free tier: 60 calls/min) |
| `polygon` | `api_key` | |
| `prixe` | `api_key` | |
| `schwab` | `api_key`, `app_secret`, `token_json`, optional `alert_webhook_url` | See below |

### Schwab setup

1. Create an app at [developer.schwab.com](https://developer.schwab.com/) (**Trader API – Individual**) with callback URL `https://127.0.0.1:8182`. New apps need manual approval (a few days) and return `401` until **Ready for Use**.
2. Generate the token on a machine with a browser:
   ```bash
   schwab-generate-token.py --token_file token.json \
     --api_key YOUR_APP_KEY --app_secret YOUR_APP_SECRET \
     --callback_url https://127.0.0.1:8182
   ```
   (The browser warns about the self-signed certificate; that is expected.)
3. Store `api_key`, `app_secret` and the full contents of `token.json` as `token_json` under provider `schwab`. Keep `SCHWAB_CALLBACK_URL` identical to the portal setting.
4. Refresh tokens expire after **7 days**; regenerate weekly (the Admin UI has a guided re-authorization). Never commit or share the token file.
5. Verify: `curl http://localhost:8000/providers`.

## Underlying Implied Volatility

IV of a stock, ETF, index or future without fetching option contracts. Choose the provider via Admin **Settings → Default Volatility Provider** or `provider=lseg|ibkr` per request; there is no cross-provider fallback.

| Endpoint | Result | Parameters |
|---|---|---|
| `GET /volatility/{symbol}` | Snapshot, tenors 30/60/90 | `sec_type=stock\|etf\|index\|future` (default `stock`), `provider`, LSEG-only `ric`, `format=json\|csv` |
| `GET /volatility/{symbol}/history` | Daily points | `start`, `end` (default: last 365 days), `tenor_days=30\|60\|90` |
| `GET /volatility/{symbol}/stats` | IV Rank and Percentile | `window=20..756` (default 252), `tenor_days` |

```bash
curl 'http://localhost:8000/volatility/SPY?sec_type=etf&provider=lseg'
curl 'http://localhost:8000/volatility/SPX/stats?sec_type=index&provider=ibkr&window=252'
curl 'http://localhost:8000/volatility/AAPL/history?provider=lseg&tenor_days=30&format=csv'
```

**Units:** IV values are annualized decimal fractions rounded to 4 places, serialized as strings (`"0.2676"` = 26.76%). IV Rank = `(current − min)/(max − min) × 100`; IV Percentile = share of prior points strictly below current × 100 (0–100, 2 decimals). Fewer than 20 history points → 404 `insufficient_history`.

| Provider | Snapshot types | History/stats types | Tenors |
|---|---|---|---|
| LSEG | stock, ETF, index, future | same | 30, 60, 90 |
| IBKR | stock, ETF, index, future | stock, ETF, index | 30 only |

- **LSEG** uses constant-maturity ATM indices over streaming (`{SYMBOL}ATMIV.U` for OPRA equities/ETFs/indices; `{ROOT}ATMIV` for futures such as ES, NQ, YM, C, W, TY). Always set `sec_type` explicitly (e.g. `ESATMIV.U` is Eversource, not the ES future). A supplied `ric` is queried as-is (e.g. `GDAXATMIV.EX`). No energy/metals futures IV.
- **IBKR** uses generic tick 106 (30-day model); futures use the nearest contract ≥7 days to last trade (`source_instrument`), and futures history is rejected. IBKR futures roots differ (ZC, ZW, ZN). `ric` is rejected.
- For commodity exposure, ETF proxies (USO, UNG, GLD, SLV) are available but are not the futures' IV. Prefer `sec_type=index` (SPX/NDX) over ES/NQ for equity-index IV.

Error codes: 400 not a volatility provider · 422 invalid input/market · 501 unsupported operation/tenor · 404 no data · 403 `PROVIDER_NOT_ENTITLED` (subscription does not cover the instrument) · 503 connectivity/config (also when no default provider is set).

## Redis Response Cache

Option chains, price history, company profile/search/news, market status and all `/volatility/*` endpoints (HTTP and their MCP counterparts) are cached in Redis for every provider. Never cached: `/prices/{symbol}/last`, option quotes, health/metrics/providers/admin, WebSockets. Redis is optional: on outage MDH serves live data and retries after 30 s. `CACHE_ENABLED=false` disables it.

| Variable | Default | Meaning |
|---|---|---|
| `CACHE_ENABLED` | `true` | Enable caching |
| `REDIS_URL` | `redis://localhost:6379/0` | Compose uses `redis://redis:6379/0` |
| `REDIS_TIMEOUT_SECONDS` | `1.0` | Per-call timeout |
| `CACHE_TTL_OPTION_CHAIN_SECONDS` | `900` | |
| `CACHE_TTL_HISTORICAL_CLOSED_SECONDS` | `604800` | Closed historical ranges |
| `CACHE_TTL_HISTORICAL_OPEN_BAR_SECONDS` / `…_INTRADAY_SECONDS` | `300` | Forming/intraday bars |
| `CACHE_TTL_COMPANY_PROFILE_SECONDS` / `…_SEARCH_…` / `…_NEWS_…` | `86400` / `3600` / `600` | |
| `CACHE_TTL_MARKET_STATUS_SECONDS` | `60` | |
| `CACHE_TTL_VOLATILITY_SECONDS` | `900` | Never extended overnight |
| `CACHE_EXTEND_WHEN_MARKET_CLOSED` | `true` | Extend chains/history to next US open; **disable for non-US symbols** |
| `REDIS_MAXMEMORY` | `256mb` | Compose Redis bound |

- TTLs can be overridden at runtime in **Admin → Settings → Response Cache** (0–30 days; 0 disables). Use **Clear cache…** to invalidate (optionally by endpoint/provider); clear after corporate actions or provider/schema changes.
- Key format: `mdh:{route_path}:{CANONICAL_SYMBOL}:{sorted_query}` with the canonical symbol percent-encoded (`F%3AES`), so `ES?sec_type=future`, `F:ES` and `/ES` share one entry; the effective provider is part of the key. MCP entries add `channel=mcp`.
- Responses carry `X-FastAPI-Cache: HIT|MISS`, `ETag`, `Cache-Control`; `If-None-Match` returns 304.
- Force live: `Cache-Control: no-cache` (refreshes entry) or `no-store` (bypass). MCP: `refresh: true`.
- Compose persists Redis in `redis-data` — don't use `docker compose down -v` unless you also want to lose the keys database.

## Admin UI

`http://localhost:9000/admin` (Compose) or `:8000/admin`: provider status, enable/disable and hot-reload of runtime settings, encrypted credential management, Schwab re-authorization, alert webhooks, cache settings.

Frontend development (React/Vite, proxies `/api` to port 8000):

```bash
cd admin && npm install && npm run dev
```

With Compose, `./admin/dist` is mounted into the container, so run `npm run build:watch` in `admin/` to see UI changes without rebuilding the image.

## MCP

With `MCP_ENABLED=true` MCP runs on the same port:

| Endpoint | Use |
|---|---|
| `POST /mcp` (and `GET /mcp`) | Streamable HTTP, e.g. Claude remote MCP: `http://localhost:8000/mcp` |
| `GET /mcp/sse` + `POST /mcp/messages?session_id=<id>` | Legacy SSE |

Tools: `get_last_price`, `get_historical_prices`, `get_option_chain`, `get_option_quote`, `get_company_profile`, `search_companies`, `get_company_news`, `get_market_status`, `get_implied_volatility`, `get_implied_volatility_history`, `get_implied_volatility_stats`. See the [MCP Guide](doc/mcp-guide.md).

## Observability

`GET /metrics` exposes Prometheus metrics with bounded labels (`provider`, `endpoint`, `status_class`). Each API request emits one JSON audit log line (`event="request_completed"`; set `X-Client-ID` to identify clients, otherwise `anonymous`).

## Deployment

**Docker:** `docker build -t market-data-hub:latest .` · `docker run --env-file .env -p 8000:8000 market-data-hub:latest`. CI pushes images to GHCR from `main`, `develop` and `v*` tags.

**Kubernetes:**

```bash
kubectl create namespace market-data-hub
kubectl create secret generic market-data-hub-secrets \
  --from-literal=app_encryption_key=$APP_ENCRYPTION_KEY -n market-data-hub
# Set your image in deploy/kubernetes.yaml, then:
kubectl apply -f deploy/kubernetes.yaml -n market-data-hub
kubectl port-forward -n market-data-hub svc/market-data-hub 8000:8000
```

Provider credentials are seeded through the Admin UI/API or a persisted `KEYS_DB_PATH`. Manifests live in `deploy/`; see [doc/deployment.md](doc/deployment.md).

## Development

```bash
uv pip install ruff
uv run ruff check app/
python skills/lint_check.py --all
uv run pytest --maxfail=1 --disable-warnings
```

API docs: Swagger UI at `/docs`, ReDoc at `/redoc`. News API details: [doc/news-api-guide.md](doc/news-api-guide.md).
