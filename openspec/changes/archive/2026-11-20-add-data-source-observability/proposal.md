## Why

MDH answers a market data request from one of three layers: the Redis response cache, the optional PostgreSQL history store (closed price bars, daily IV points, earnings events) or a live provider call. Clients cannot see which layer answered or where the time went. VisioTrade measures the whole MDH call (`mdhMs`) and reads `X-FastAPI-Cache` (`HIT`/`MISS`), but a miss that is answered from PostgreSQL in 15 ms and a miss that waits 1.8 s for Schwab look the same. On the MDH side, `/metrics` only has request totals per coarse endpoint group (`mdh_http_requests_total`, `mdh_http_request_duration_seconds`) and `mdh_history_store_reads_total`; the audit log line `request_completed` has neither the symbol nor any layer timing, and there is no request ID that links an MDH log line to a VisioTrade trace.

Without these numbers there is no basis for the next decisions: which data types should also be kept in PostgreSQL, which TTLs are too short, and whether request coalescing on MDH would pay off.

## What Changes

- **Request telemetry context**: one per data request (HTTP route or MCP tool call), bound in a `ContextVar` by the observability middleware or the MCP dispatcher. Redis operations, store transactions and provider calls record spans into it; the response layer (`X-Data-Source`), the data provider and the cache status are recorded by the cache wrapper and the services.
- **Response headers** on the 14 market data routes (prices, options, companies, market status, volatility, earnings):
  - `Server-Timing` (W3C) with the entries `redis`, `db`, `provider`, `redis-write` (each present only when that layer was used) and `total`, for example `redis;desc="miss";dur=1.4, db;desc="partial";dur=11.8, provider;desc="schwab";dur=412.6, redis-write;dur=0.9, total;dur=431.2`.
  - `X-Data-Source`: `redis` | `postgres` | `provider` | `postgres+provider`.
  - `X-Data-Provider`: the provider whose data is in the response (differs from the requested provider for stale fallbacks; `a+b` for composed earnings).
  - `X-FastAPI-Cache` stays as the cache status header (`HIT`/`MISS`, absent when the cache is not used) and is now documented. No additional `X-Cache` header.
- **`X-Request-ID`** on every HTTP response: taken from a valid inbound header or generated, bound to all log records of the request.
- **Prometheus metrics** (new, alongside the existing ones): `mdh_data_requests_total`, `mdh_data_request_duration_seconds`, `mdh_cache_operation_duration_seconds`, `mdh_db_operation_duration_seconds`, `mdh_provider_request_duration_seconds` and `mdh_cache_concurrent_miss_total`, with fixed, enumerated label values (no symbols) and a 1 ms–30 s bucket layout.
- **Structured logs**: the existing `request_completed` audit event of data routes gets `request_id`, `channel`, `endpoint`, `symbol`, `data_source`, `data_provider`, `cache_status`, `ttl_seconds`, `redis_ms`, `db_ms`, `provider_ms` and `total_ms`. MCP tool calls emit `mcp_tool_completed` with the same fields.
- **OpenAPI and CORS**: the headers are documented on every data route; `Access-Control-Expose-Headers` lists `Server-Timing`, `X-FastAPI-Cache`, `X-Data-Source`, `X-Data-Provider`, `X-Request-ID` and `X-MDH-Data-As-Of`.
- **Grafana dashboard handoff specification** (`grafana-dashboard-spec.md`, moved to `doc/` on implementation): datasource inputs, variables, metric/label/log-field reference and every panel with type, unit, thresholds and query, as the input for generating importable dashboard JSON.
- **Analysis record** in `design.md`: current TTLs per endpoint, where PostgreSQL is used, and why request coalescing is deferred (measured by `mdh_cache_concurrent_miss_total` instead).
- **BREAKING (spec only)**: the `observability-metrics` requirement "only three labels" is replaced by a per-metric label budget. Existing metric names, labels and values do not change.

## Capabilities

### New Capabilities
- `data-source-observability`: request telemetry context, data-source and timing headers, request ID, data-request metrics, layer timing metrics, concurrent-miss counter and the new log fields, for HTTP and MCP.

### Modified Capabilities
- `observability-metrics`: the fixed three-label rule becomes a per-metric enumerated label budget; the provider label set is updated to the providers that exist today.

## Impact

- **Code**: `app/observability/` (new `telemetry.py`; `metrics.py` new instruments; `middleware.py` headers, request ID, log fields), `app/cache.py` (Redis timing, cache status, TTL, concurrent-miss tracking), `app/store/engine.py` (`session_scope` timing with an operation name) and its call sites, `app/store/sync.py` and `app/services/*` (store result and data provider), `app/providers/base.py` (timed provider interface methods), `app/api/routes_*.py` (OpenAPI headers), `app/api/mcp.py` (per-tool telemetry), `app/main.py` (CORS `expose_headers`), `app/logging_config.py` (`request_id` in stdlib JSON logs).
- **API**: additive response headers only; JSON and CSV bodies are unchanged. VisioTrade can read `Server-Timing` and `X-Data-Source` in its MDH client (change in the VisioTrade repository, not part of this change).
- **Metrics**: about six new metric families; worst-case series budget in `design.md` (D9). Existing series are unchanged, so existing dashboards and alerts keep working.
- **Logs**: `request_completed` lines of data routes grow by about 300 bytes.
- **Dependencies**: none.
- **Not covered**: request coalescing or stampede protection for the Redis layer (measured only), new PostgreSQL datasets, TTL changes, OpenTelemetry tracing, browser `Timing-Allow-Origin`, the WebSocket price stream, and the generated dashboard JSON itself (next step, from the handoff specification).
