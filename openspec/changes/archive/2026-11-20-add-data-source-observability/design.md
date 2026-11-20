## Context

Analysis of the code base on 2026-11-20 (version 1.6.0).

### Layers a market data request can pass

| Layer | Where | Used by | Today's observability |
|---|---|---|---|
| Redis response cache | `fastapi-cache2` via `app.cache.cache()` (HTTP) and `app.cache.cached_call()` (MCP, keys with `channel=mcp`); backend `FailOpenRedisBackend` (`get_with_ttl`, `set`) | 12 of the 14 data routes (`/prices/{symbol}/last` and `/options/{symbol}/quote/{id}` are not cached) | `X-FastAPI-Cache: HIT|MISS` set by the library; absent when the cache is disabled or the client sends `Cache-Control: no-store`. `Cache-Control: max-age` rewritten by `CacheControlMiddleware` from `scope["mdh_cache_ttl"]` |
| PostgreSQL history store | `app/store/sync.py` (`HistorySync.serve`, per-series `asyncio.Lock`), `app/store/earnings_repository.py`; all transactions through `engine.session_scope()`; optional (`DATABASE_URL`), fail-open with 30 s cooldown | `prices:history` (only intervals listed in the provider's `history_store_intervals`, default `1d`), `volatility:history`, `volatility:stats`, `earnings:calendar`, `earnings:next`, `companies:earnings` | `mdh_history_store_reads_total{dataset, result}` with `result` ∈ `store`, `tail_sync`, `backfill`, `full_load`, `reload`, `stale`, `fallback_provider`, `bypass` |
| Earnings fallback keys | `earnings_service._load_ephemeral` / `_cache_ephemeral` on the budget Redis client, only when the store is disabled | earnings routes | none |
| Provider | services enter `registry.use_*_provider(name)` and await interface methods of `app/providers/base.py`; metered HTTP providers (`alphavantage`, `financialdatasets`, `earningsapi`) pace, consume the request budget and retry inside `MeteredHttpProvider._request`; `ibkrweb` paces internally; `ibkr` (socket) and `lseg` (sync library in threads) have no HTTP layer; `lseg` has its own 5 s quote cache (`LSEG_CACHE_TTL_SECONDS`) | all data routes | `mdh_provider_upstream_requests_total{provider}` (attempts of metered providers), `mdh_provider_rate_limits_total{provider}` |

Consequences for this change:

- PostgreSQL is not a general second cache level. Options chains, company profile/search/news, market status, volatility snapshots, last price and option quotes never touch it. A `db` timing appears only on the six store-backed routes.
- A store-backed answer is often composed: stored closed bars plus the forming bar or a missing tail from the provider (`tail_sync`, `backfill`). The response layer therefore needs a combined value (`postgres+provider`).
- Store transactions and provider calls interleave inside one request (read series → provider tail → write → read range), so per-layer durations must be measured as spans and merged, not as one stopwatch per layer.

### Existing observability conventions

- Metrics live in `app/observability/metrics.py` on a private `CollectorRegistry`, with `mdh_` prefix, `_total` counters, `_seconds` histograms, label values clamped to `frozenset`s by `_label_value()`.
- `ObservabilityMiddleware` (pure ASGI, so `ContextVar`s set before `await self.app(...)` are visible in the endpoint) records `mdh_http_*` and writes the structlog audit event `request_completed` (`client_id`, `method`, `path` route template, `provider`, `params` query only, `status_code`, `duration_ms`) for all paths except `/health`, `/metrics`, `/docs`, `/redoc`, `/openapi.json`, `/admin`, `/api/admin/auth`.
- Stdlib logs are JSON via `JsonRequestFormatter` with `provider` from structlog contextvars. There is no request ID anywhere.
- The endpoint classifier of `mdh_http_*` is coarse (`prices`, `options`, `news`, `companies`, …); volatility, earnings and market status fall into `other`.

### Consumer

VisioTrade calls MDH only from its Python backend, so CORS does not affect it. Its `AsyncCache` already coalesces concurrent fetches of one key per replica (single-flight), its MDH client maps `X-FastAPI-Cache` to the trace field `upstreamCache`, and it computes `mdhMs` as the union of request intervals (VisioTrade change `data-load-transparency`, D4). It would read `Server-Timing` once MDH sends it.

### Current TTLs per endpoint (defaults; runtime values come from `system_settings`)

| Route key | Policy field | Default | Market-closed extension |
|---|---|---|---|
| `options:chain` | `option_chain_seconds` | 900 s | yes, until next open (cap 7 d) |
| `prices:history` closed range | `historical_closed_seconds` | 604800 s (7 d) | – |
| `prices:history` open range, daily+ | `historical_open_bar_seconds` | 300 s | yes |
| `prices:history` open range, intraday | `historical_intraday_seconds` | 300 s, capped at bar length | yes |
| `companies:profile` | `company_profile_seconds` | 86400 s | no |
| `companies:search` | `company_search_seconds` | 3600 s | no |
| `companies:news` | `company_news_seconds` | 600 s | no |
| `market-status` | `market_status_seconds` | 60 s, capped at next session transition | no |
| `volatility:snapshot`, `volatility:stats` | `volatility_seconds` | 900 s | no |
| `volatility:history` | `volatility_seconds`, closed range `historical_closed_seconds` | 900 s / 7 d | no |
| `earnings:calendar`, `earnings:next`, `companies:earnings` | `earnings_seconds` | 21600 s | no |
| `prices:last`, `options:quote` | not cached | – | – |

Store resynchronisation of a due tail is throttled by `HISTORY_STORE_RESYNC_SECONDS` (300 s).

### Request coalescing assessment

- Already coalesced: concurrent requests for one store series (`HistorySync` per-series lock) and earnings gathering (`_gather_locked`). VisioTrade coalesces its own concurrent fetches per key and replica.
- Not coalesced: concurrent Redis misses of the same key on one MDH replica (`fastapi-cache2` has no stampede protection), e.g. two VisioTrade replicas, or VisioTrade and an MCP agent requesting the same chain at once.
- Decision: no coalescing in this change. `mdh_cache_concurrent_miss_total` counts how often a miss starts while another miss for the same key is in flight on the replica. If it is a relevant share of `mdh_data_requests_total{cache_status="miss"}` for an endpoint with slow providers, coalescing becomes its own change.

## Goals / Non-Goals

**Goals:**
- Every data response states which layer answered, which provider's data it contains and how long Redis, PostgreSQL and the provider took.
- Hit ratios per layer and latency percentiles per layer are queryable in VictoriaMetrics without symbols in labels.
- Slow symbols and cache misses are findable in Loki, with a request ID that links MDH logs to client traces.
- A dashboard specification that can be turned into importable dashboard JSON without further questions.

**Non-Goals:**
- Request coalescing, TTL changes, new store datasets (decided later from the data).
- OpenTelemetry or distributed tracing.
- Changes to existing metric names, labels or the `X-FastAPI-Cache` header.
- Telemetry for admin, health, `/providers`, `/metrics` and the WebSocket stream.

## Decisions

### D1 — One telemetry object per data request, bound in a ContextVar

`app/observability/telemetry.py` defines `RequestTelemetry` (request ID, channel, endpoint key, symbol, start time, span lists per layer, cache status, TTL, store outcome, data provider, provider names called) and a `ContextVar[RequestTelemetry | None]`. `ObservabilityMiddleware` creates it for every HTTP request and stores it in the ContextVar and in `scope["mdh_telemetry"]`. The MCP dispatcher creates one per `tools/call`.

The object is mutable and the ContextVar holds a reference, so tasks started with `asyncio.gather`/`create_task` (which copy the context) and `asyncio.to_thread` record into the same object. Spans that end after the response headers were sent are ignored for headers but still counted in metrics.

- *Alternative:* a custom wrapper around each route. Rejected: the store and the providers sit several calls below the route, and the existing `response_meta` already shows that a ContextVar is the established way to pass per-request state down.
- *Alternative:* `BaseHTTPMiddleware`. Rejected: it runs the endpoint in another task, so values set below are not visible to the middleware, and it buffers streaming responses.

### D2 — Recording points

| Layer | Recording point | Span |
|---|---|---|
| Redis | `FailOpenRedisBackend.get_with_ttl` and `set` (covers HTTP decorator and `cached_call`); earnings fallback keys in `_load_ephemeral`/`_cache_ephemeral` | one per operation; a read before the response is a `redis` span, a write after the loader a `redis-write` span |
| PostgreSQL | `engine.session_scope(operation="read"|"write")`; every call site passes the operation (a transaction that writes anything is `write`) | one per transaction |
| Provider | the public interface methods of `app/providers/base.py` (`get_historical_prices`, `get_last_price`, `get_market_status`, `get_company_profile`, `search_companies`, `get_option_chain`, `get_option_quote`, `get_company_news`, `get_upcoming_earnings`, `get_symbol_earnings`, `get_earnings_for_date`, `get_earnings_history`, `get_implied_volatility`, `get_implied_volatility_history`), wrapped once per concrete class by `__init_subclass__` on the base interfaces; a ContextVar guard records only the outermost call when one interface method calls another | one per outermost call |

Wrapping on the class covers every call path (including `registry.get_provider_instance`) without proxies that would break `isinstance` checks in services. `test_connection` and admin/session methods are not wrapped.

The cache status, TTL and store outcome are set by `app.cache` (`cache()` wrapper, `get_with_ttl`, `set`) and by `HistorySync._serve_locked` / `EarningsService`. The data provider is set where the data is produced: the effective provider by default, `meta.source_provider` for stale fallbacks, `a+b` for composed earnings.

### D3 — Per-layer duration is the union of its spans, wall clock

`redis_ms`, `db_ms` and `provider_ms` are the length of the union of the layer's span intervals, clipped to the request window (start of telemetry until response start). This is the same rule VisioTrade uses for `mdhMs`. It includes everything the layer blocks the request for: pacing waits, budget checks, retries with backoff, gateway pacing and connection setup. Parallel provider calls therefore count once, so a layer duration never exceeds `total`. Waiting on the store series lock or the provider acquire lock belongs to no layer and shows only in `total`.

The per-call histograms (D7) measure each span individually; they answer "how slow is provider X", while the union answers "how long did this request wait for the provider layer".

### D4 — Response layer and Server-Timing values

The store outcome is normalised to four values:

| Store result (history) | Earnings | Store outcome (`db` desc) | `X-Data-Source` |
|---|---|---|---|
| `store` | answered from store without provider call | `hit` | `postgres` |
| `tail_sync`, `backfill` | store plus provider call | `partial` | `postgres+provider` |
| `full_load`, `reload` | store empty for the request, all data from provider | `miss` | `provider` |
| `stale`, `fallback_provider` | stored data after provider failure | `stale` | `postgres` |
| `bypass` / store disabled or in cooldown | – | no `db` entry | `provider` |

Without a store outcome: a cache hit is `redis`; an earnings answer only from the fallback keys is `redis`; everything else is `provider`.

`Server-Timing` lists entries in this order, each only if used: `redis;desc="<hit|miss|bypass>";dur=…`, `db;desc="<hit|partial|miss|stale>";dur=…`, `provider;desc="<data provider>";dur=…`, `redis-write;dur=…`, `total;dur=…`. Durations are milliseconds with one decimal. `desc` values are quoted strings so `a+b` is valid. `total` is measured from the start of the middleware until `http.response.start`; the existing `duration_ms` of the audit log keeps its meaning (until the last body chunk).

### D5 — Cache status

`cache_status` (metrics, logs, `redis` desc):

- `hit`: served from the response cache, including a `304 Not Modified` revalidation.
- `miss`: the cache was read, had no entry, and the result was written (or would have been written but the write failed).
- `bypass`: the cache was not used for this answer: route not cached, caching disabled, Redis in cooldown, effective TTL 0 prevented caching a fresh response, stale answer (never cached), or the client sent `Cache-Control: no-cache`/`no-store`; MCP `refresh=true`. Runtime TTL changes apply only to future writes; an existing entry still counts as a hit until it expires.

`X-FastAPI-Cache` is left exactly as the library sets it. It differs from `cache_status` in two cases, both documented in OpenAPI: `no-cache` (header `MISS`, status `bypass`) and TTL 0 or Redis cooldown (header `MISS`, status `bypass`). No `X-Cache` header is added: VisioTrade already reads `X-FastAPI-Cache`, and `X-Data-Source` carries the layer.

`ttl_seconds`: on a miss the effective TTL written (from `scope["mdh_cache_ttl"]`, `0` when not written); on a hit the remaining TTL returned by `get_with_ttl`; `null` on bypass.

On a hit the data provider comes from the existing cache key. For default earnings keys containing `upcoming+history`, select the roles requested by `kind`, omit unconfigured `-` roles, and preserve upcoming-first order. This affects attribution only, not cache keys or response bodies.

For `earnings:next`, `X-Data-Provider` and the corresponding log and metric attribution always name the effective upcoming provider. The optional PostgreSQL enrichment `last_reported` retains its own `provider` field in the body and can affect the data source, but not the response's provider name. The same rule applies to `get_next_earnings` and cache hits.

### D6 — Request ID

`X-Request-ID` is taken from the request when it matches `^[A-Za-z0-9._:-]{1,128}$`, otherwise a new UUID4 hex is generated. It is set on every HTTP response (also errors and non-data routes), bound with `structlog.contextvars.bind_contextvars(request_id=…)` so all structlog lines carry it, and added to `JsonRequestFormatter` output via `RequestContextFilter`. Accepting a client value lets VisioTrade pass its own trace ID; the pattern prevents log injection.

### D7 — Metrics

New instruments in `app/observability/metrics.py`; all label values are clamped to fixed sets.

| Metric | Type | Labels |
|---|---|---|
| `mdh_data_requests_total` | counter | `channel`, `endpoint`, `source`, `provider`, `cache_status` |
| `mdh_data_request_duration_seconds` | histogram (total) | `channel`, `endpoint`, `source`, `provider` |
| `mdh_cache_operation_duration_seconds` | histogram | `endpoint`, `operation` (`read`, `write`), `status` (`ok`, `error`) |
| `mdh_db_operation_duration_seconds` | histogram | `endpoint`, `operation` (`read`, `write`), `status` (`ok`, `error`) |
| `mdh_provider_request_duration_seconds` | histogram | `provider`, `operation` (interface method), `status` (`success`, `not_found`, `timeout`, `error`) |
| `mdh_cache_concurrent_miss_total` | counter | `endpoint` |

Label values:

- `channel`: `http`, `mcp`.
- `endpoint`: the 14 route keys `prices:history`, `prices:last`, `options:chain`, `options:quote`, `market-status`, `companies:profile`, `companies:search`, `companies:news`, `companies:earnings`, `volatility:snapshot`, `volatility:history`, `volatility:stats`, `earnings:calendar`, `earnings:next`, plus `other` (spans outside a data request, e.g. startup probes). MCP tools map 1:1 (`get_option_chain` → `options:chain`, …; `get_earnings_calendar` → `earnings:calendar`).
- `source`: `redis`, `postgres`, `provider`, `postgres+provider`.
- `provider`: the existing `PROVIDERS` set (`ibkr`, `ibkrweb`, `lseg`, `finnhub`, `polygon`, `prixe`, `schwab`, `alphavantage`, `financialdatasets`, `earningsapi`, `none`) plus `multiple` for composed earnings answers. It is the data provider (`X-Data-Provider`), not the requested one.
- `operation` (provider): the 14 interface method names of D2, otherwise `other`.

`mdh_data_requests_total` and `mdh_data_request_duration_seconds` count completed data requests with status 2xx or 304. Failed requests stay in `mdh_http_requests_total` and, for provider failures, in `mdh_provider_request_duration_seconds{status!="success"}`; mixing error latencies into the per-source histogram would hide the layer comparison.

The name `mdh_data_request_duration_seconds` (not `mdh_request_duration_seconds`) avoids confusion with the existing `mdh_http_request_duration_seconds`. `mdh_db_operation_duration_seconds` (not `…_query_…`) because one observation is one transaction, which can hold several statements.

Status mapping for provider calls: `DataNotFoundError` → `not_found`; `ProviderTimeoutError`, `asyncio.TimeoutError`, `httpx.TimeoutException` → `timeout`; other exceptions → `error`; `asyncio.CancelledError` is not observed.

### D8 — Buckets

All new histograms share `(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)` seconds (14 buckets plus `+Inf`): 1–10 ms resolves Redis, 5–250 ms PostgreSQL, 100 ms–30 s providers (IBKR chains, LSEG, retries with backoff up to `PROVIDER_REQUEST_TIMEOUT` 10 s × retries). One layout keeps panels comparable and `histogram_quantile` across sources consistent. The existing `mdh_http_request_duration_seconds` buckets are unchanged.

### D9 — Cardinality budget

Histogram series per label combination = 15 buckets (incl. `+Inf`) + `_sum` + `_count` = 17. Worst case (every label combination) versus the realistic case (a route has 1–4 providers; `cache_status` is implied by `source` except for `miss`/`bypass`):

| Metric | Worst case series | Realistic |
|---|---|---|
| `mdh_data_requests_total` | 2 × 15 × 4 × 12 × 3 = 4320 | ≈ 300 |
| `mdh_data_request_duration_seconds` | 2 × 15 × 4 × 12 × 17 = 24480 | ≈ 1500 |
| `mdh_cache_operation_duration_seconds` | 15 × 2 × 2 × 17 = 1020 | ≈ 400 |
| `mdh_db_operation_duration_seconds` | 15 × 2 × 2 × 17 = 1020 | ≈ 200 |
| `mdh_provider_request_duration_seconds` | 12 × 15 × 4 × 17 = 12240 | ≈ 800 |
| `mdh_cache_concurrent_miss_total` | 15 | 15 |

About 3,200 realistic series per replica, well inside VictoriaMetrics' comfort zone. The budget is part of the modified `observability-metrics` spec, and the label sets are enforced by `_label_value()`.

### D10 — Log fields

`request_completed` of a data route gets: `request_id`, `channel` (`http`), `endpoint`, `symbol` (canonical symbol of the path parameter, `null` for list routes such as `earnings:calendar`), `data_source`, `data_provider`, `cache_status`, `ttl_seconds`, `redis_ms`, `db_ms`, `provider_ms`, `total_ms` (all four as numbers, `0` when the layer was not used, so LogQL `unwrap` never fails). `provider` (requested/effective provider) and `duration_ms` keep their meaning. Non-data routes get `request_id` only.

MCP tool calls emit one structlog event `mcp_tool_completed` with the same fields, `channel` `mcp`, plus `tool` and `status` (`ok`/`error`).

Symbols stay log fields; the log shipper must not promote them to Loki stream labels.

### D11 — OpenAPI and CORS

A shared `DATA_RESPONSE_HEADERS` dict (description and schema for `Server-Timing`, `X-Data-Source` with enum, `X-Data-Provider`, `X-FastAPI-Cache` with enum and the two deviations of D5, `X-Request-ID`, `Cache-Control`, and for CSV `X-MDH-Data-As-Of`) is applied as `responses={200: {"headers": …}}` on the 14 data routes. `CORSMiddleware` gets `expose_headers=["Server-Timing", "X-FastAPI-Cache", "X-Data-Source", "X-Data-Provider", "X-Request-ID", "X-MDH-Data-As-Of"]`. This costs nothing and serves a future browser client; it is not needed by VisioTrade (server-side). `Timing-Allow-Origin` is not set.

### D12 — Dashboard handoff as a document, not JSON

The dashboard is specified in `doc/observability/grafana-dashboard-spec.md` with datasource inputs (`DS_PROMETHEUS`, `DS_LOKI`) and a textbox variable for the Loki stream selector (default `{app="market-data-hub"}`), because datasource names and stream labels belong to the deployment (no collector configuration exists in this repository). PromQL is checked with `promtool`; LogQL is checked against captured log lines using `logcli --stdin` for log queries and a local Loki instance for metric queries, which stdin mode does not support (task 7.3).

## Risks / Trade-offs

- **[Overhead per request]** → a few `perf_counter` calls and list appends per span; metrics and headers are computed once per request. Measured in task 8.2; expected below 0.1 ms.
- **[Spans recorded after response start]** (shielded flights, background writes) → excluded from headers and log layer durations, still observed in histograms; documented.
- **[Provider methods calling each other]** → ContextVar guard records the outermost call only; a unit test covers an options provider calling `get_last_price` inside `get_option_chain`.
- **[Internal provider caches]** (`lseg` quote cache, `ibkr` contract caches) → a provider span can be ~0 ms although `X-Data-Source` is `provider`; documented in the dashboard spec so that low provider latencies are not misread.
- **[`X-FastAPI-Cache` and `cache_status` disagree for `no-cache`/TTL 0]** → documented in OpenAPI and the dashboard spec; dashboards use the metric.
- **[Information disclosure]** → headers expose provider names and timings to API clients. All clients are authenticated internal consumers (VisioTrade, TradeSensei); no credentials, hosts or symbols beyond the request are exposed.
- **[Label value `postgres+provider` contains a regex metacharacter]** → Grafana escapes multi-value and "All" variables for Prometheus and Loki; hand-written queries use `source!~"redis|postgres"` or exact matches instead of regex on this value.

## Migration Plan

Additive. Deploy, check `/metrics` for the new families and one data response for the headers, then import the dashboard generated from the handoff specification. Rollback is a redeploy of the previous version; no data migration.

## Implementation verification (2026-11-20)

- **Cache-hit overhead:** warmed, in-process HTTPX ASGI requests to the real chain route, fake Redis, 50 option quotes and audit rendering enabled (stdout discarded). Alternated legacy and instrumented requests in the same event loop, 1,000 cache hits per arm after 50 warmups. The legacy median was **5.4168 ms** and the instrumented median **5.6012 ms**; the median paired overhead was **0.1636 ms** (difference of medians **0.1845 ms**). An initial separate-process run also exceeded 0.1 ms (+0.1459 ms difference of medians). The local target was **not met**. Measure representative production traffic before drawing conclusions about fleet overhead.
- **Dependency smoke test:** disposable Docker Compose with Redis 7 and PostgreSQL 16, production cache/store paths and a deterministic stand-in provider. `curl -i` confirmed the four sources `provider`, `redis`, `postgres` and `postgres+provider`. `/metrics` exposed all six families; the audit event matched the supplied `X-Request-ID`. The temporary stack was removed afterwards.

## Open Questions

- Real Loki stream labels of the production collector (the dashboard default `{app="market-data-hub"}` is a placeholder).
- Whether TradeSensei calls MDH from a browser; if so its origin must be added to `allow_origins` (separate change).
