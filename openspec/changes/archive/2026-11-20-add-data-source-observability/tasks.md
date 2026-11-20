Priority order: groups 1–3 deliver the headers VisioTrade can read; 4 the metrics; 5 the logs; 6 MCP; 7 the dashboard handoff; 8 verification.

## 1. Telemetry core (P1)

- [x] 1.1 `app/observability/telemetry.py`: `RequestTelemetry` (request ID, channel, endpoint, symbol, start, span lists for `redis`, `redis-write`, `db`, `provider`, cache status, TTL, store outcome, data provider), `ContextVar`, `current_telemetry()`, `span(layer, …)` async context manager, `union_ms(spans, start, until)`; route-key table for the 14 data routes and the 13 MCP tools (design D7)
- [x] 1.2 Unit tests: interval union (disjoint, overlapping, nested, clipped to the response start), spans from `asyncio.gather` and `asyncio.to_thread` land in the same object, no context → recording is a no-op
- [x] 1.3 Request ID in `ObservabilityMiddleware`: validate inbound `X-Request-ID` (`^[A-Za-z0-9._:-]{1,128}$`) or generate UUID4 hex, bind via `structlog.contextvars`, set the response header on every HTTP response; `RequestContextFilter`/`JsonRequestFormatter` add `request_id`; tests for valid, invalid, missing, error response, `/health`

## 2. Recording points (P1)

- [x] 2.1 `app/cache.py`: time `FailOpenRedisBackend.get_with_ttl` (read span, remaining TTL on hit) and `set` (`redis-write` span, effective TTL); in `cache()` and `cached_call()` set the cache status per design D5 (hit incl. 304, miss, bypass for uncached/disabled/cooldown/TTL 0 preventing a fresh write/stale/`no-cache`/`no-store`/MCP `refresh`)
- [x] 2.2 `app/store/engine.py`: `session_scope(operation="read"|"write")` records a `db` span; update every call site in `app/store/sync.py`, `app/store/repository.py` users and `app/services/earnings_service.py` (transactions that write pass `write`)
- [x] 2.3 `app/providers/base.py`: `__init_subclass__` on the provider interfaces wraps the 14 public interface methods (design D2) of each concrete class once; ContextVar guard so nested interface calls record only the outermost; not `test_connection`; test with a fake options provider whose `get_option_chain` calls `get_last_price`
- [x] 2.4 Audit: grep for provider calls that bypass the interface methods (`get_provider_instance(...)` followed by data calls) and list them in this task; wrap or document each
  - `PriceService._native` reads capability metadata only. Admin `_provider_for_support` and `_provider_status` inspect capabilities/status; `_enabled_ibkr_web` and the IBKR Web status route call session methods only; the admin connection test calls `test_connection`. None is a data request.
  - `MeteredHttpProvider.test_connection` calls the instrumented `get_last_price` internally; this probe suppresses timing so it does not count as a provider data request.
- [x] 2.5 Store outcome: `HistorySync._serve_locked` maps its `result` to `hit`/`partial`/`miss`/`stale` (design D4) on the telemetry; `price_service`/`volatility_service` set nothing for `bypass`; `EarningsService` sets `hit` (store only), `partial` (store + provider), `stale`, and source `redis` for answers only from the fallback keys (`_load_ephemeral` and `_cache_ephemeral` record redis spans)
- [x] 2.6 Data provider: effective provider by default; `meta.source_provider` for stale fallbacks; `a+b` for composed earnings (upcoming first); role-aware cache hit attribution; only the upcoming provider for next earnings

## 3. Response headers, OpenAPI, CORS (P1)

- [x] 3.1 `ObservabilityMiddleware`: on `http.response.start` of a data route compute `total`, the layer unions and set `Server-Timing` (order and format of design D4), `X-Data-Source`, `X-Data-Provider` for 2xx/304; `Server-Timing` with `total` only for errors
- [x] 3.2 `DATA_RESPONSE_HEADERS` (design D11) applied as `responses={200: {"headers": …}}` on the 14 data routes; test that `/openapi.json` lists them for each route
- [x] 3.3 `app/main.py`: `expose_headers` for the six headers; test with an allowed origin
- [x] 3.4 Route tests (fakeredis or the existing cache test fixtures, in-memory store fixture, fake providers):
  - Redis hit: `redis;desc="hit"` + `total`, `X-Data-Source: redis`, `X-Data-Provider` from the key, `X-FastAPI-Cache: HIT`
  - Store hit (daily history, settled market): `redis;desc="miss"`, `db;desc="hit"`, no `provider`, `X-Data-Source: postgres`
  - Store partial (session, tail from provider): `db;desc="partial"`, `provider`, `X-Data-Source: postgres+provider`
  - Provider miss (option chain): `redis;desc="miss"`, `provider;desc="<name>"`, `redis-write`, no `db`, `X-Data-Source: provider`
  - Stale fallback: `X-Data-Source: postgres`, `X-Data-Provider` = source provider
  - Uncached route (`/prices/{symbol}/last`): no `redis` entry, cache status `bypass`
  - `Cache-Control: no-cache`: `redis;desc="bypass"`, `X-FastAPI-Cache: MISS`
  - CSV response carries the same headers
  - Error response: `Server-Timing` `total` only, no `X-Data-Source`
  - Every layer `dur` ≤ `total`

## 4. Metrics (P2)

- [x] 4.1 `app/observability/metrics.py`: the six instruments, label sets and buckets of design D7/D8; `multiple` provider value for data metrics; extend `PROVIDERS` tests
- [x] 4.2 Record `mdh_data_requests_total`/`mdh_data_request_duration_seconds` once per successful data request (middleware for HTTP, dispatcher for MCP); not for failures
- [x] 4.3 Record cache, DB and provider operation histograms at the recording points of group 2 (also outside requests with `endpoint="other"`); provider status mapping (`not_found`, `timeout`, `error`, cancellation not observed)
- [x] 4.4 `mdh_cache_concurrent_miss_total`: in-flight miss key registry per process, registered on a read miss, released when the request's telemetry closes (also on error); test with two concurrent requests and one sequential pair
- [x] 4.5 Metric tests: increments for Redis hit, store hit, provider miss, MCP call, failure not counted; bucket boundaries; unknown label values clamped; no symbol in any label (scan `/metrics` output)

## 5. Logs (P2)

- [x] 5.1 Extend `request_completed` of data routes with the fields of design D10 (`symbol` via `parse_symbol` of the path parameter; numbers, `0` for unused layers; `ttl_seconds` per D5); non-data routes only `request_id`
- [x] 5.2 Tests with `structlog.testing.capture_logs`: fields for hit, store hit, provider miss and a failed request; no payload in the log

## 6. MCP (P2)

- [x] 6.1 `app/api/mcp.py`: one telemetry context per `tools/call` (channel `mcp`, endpoint from the tool table, symbol from the arguments); emit `mcp_tool_completed` and record the data metrics; no headers
- [x] 6.2 MCP tests: metric increment with `channel="mcp"`, log event fields, `refresh=true` → `bypass`

## 7. Dashboard handoff (P3)

- [x] 7.1 Move `grafana-dashboard-spec.md` to `doc/observability/grafana-dashboard-spec.md` and link it from `README.md` (observability section)
- [x] 7.2 Update the metric/label/log reference in the handoff document if implementation details changed names or values
- [x] 7.3 Check every PromQL query with `promtool` (rules file with sample Grafana variables) and every LogQL query against captured `request_completed` lines from the tests. Use `logcli query --stdin` for log queries and local Loki for metric queries, which stdin mode does not support; record the check in the document

## 8. Verification and release (P3)

- [x] 8.1 `uv run pytest` green; `ruff` and `mypy` clean
- [x] 8.2 Overhead check: 1,000 cached chain requests with and without telemetry in a local benchmark; record the median difference in `design.md` (target below 0.1 ms)
- [x] 8.3 Local smoke test against Docker Compose (Redis + PostgreSQL): one request per data source, inspect headers with `curl -i`, `/metrics` families and a log line
- [x] 8.4 `CHANGELOG.md`, version bump (minor: additive headers and metrics), `openspec validate add-data-source-observability --strict`
- [x] 8.5 Inform VisioTrade (separate change there): `Server-Timing`, `X-Data-Source`, `X-Data-Provider` and `X-Request-ID` are available in the local MDH 1.7.0 implementation; VisioTrade can send its trace ID as `X-Request-ID`. Handoff saved in the VisioTrade project and [documented here](../../../../doc/observability/visiotrade-handoff.md).
