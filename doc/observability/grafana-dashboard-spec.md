# Grafana Dashboard Handoff: MDH Data Sources & Latency

Build instructions for an importable Grafana dashboard (schema version 39+, Grafana 10.4 or newer) that shows where Market Data Hub answers come from (Redis, PostgreSQL, provider) and how long each layer takes. Everything a generator needs is in this document; names and values are binding. Metric and log definitions come from OpenSpec change `add-data-source-observability`.

## 1. Dashboard

| Property | Value |
|---|---|
| Title | `MDH – Data Sources & Latency` |
| UID | `mdh-data-sources` |
| Tags | `mdh`, `market-data-hub`, `cache`, `latency` |
| Time range | `now-24h` to `now` |
| Refresh | `1m` (options `30s`, `1m`, `5m`, `15m`) |
| Timezone | `browser` |
| Graph tooltip | shared crosshair (`graphTooltip: 1`) |

## 2. Datasources (import inputs)

The JSON SHALL use `__inputs` and reference datasources only through them, so it imports into any Grafana:

| Input name | Type | `pluginId` | Used by |
|---|---|---|---|
| `DS_PROMETHEUS` | `datasource` | `prometheus` (VictoriaMetrics is queried through the Prometheus datasource type) | rows A–E |
| `DS_LOKI` | `datasource` | `loki` | row F |

Panel and target datasource references: `{"type": "prometheus", "uid": "${DS_PROMETHEUS}"}` and `{"type": "loki", "uid": "${DS_LOKI}"}`.

## 3. Variables

All multi-value variables: `multi: true`, `includeAll: true`, `allValue: ".*"`, default `All` unless stated. Grafana escapes selected values for regex matchers, so the value `postgres+provider` is safe in `=~"$source"`.

| Name | Label | Type | Definition | Default |
|---|---|---|---|---|
| `channel` | Channel | custom | `http,mcp` | `http` |
| `endpoint` | Endpoint | query (`DS_PROMETHEUS`) | `label_values(mdh_data_requests_total, endpoint)`, refresh on time range change, sort alphabetical | All |
| `provider` | Provider | query (`DS_PROMETHEUS`) | `label_values(mdh_data_requests_total{endpoint=~"$endpoint"}, provider)`, refresh on time range change | All |
| `source` | Data source | custom | `redis,postgres,provider,postgres+provider` | All |
| `loki_selector` | Loki stream selector | textbox | – | `{app="market-data-hub"}` (placeholder; set to the real stream labels of the deployment) |
| `slow_ms` | Slow request threshold (ms) | textbox | – | `500` |
| `symbol` | Symbol (regex) | textbox | – | `.*` |

## 4. Metric, label and log reference

### 4.1 Metrics (VictoriaMetrics / Prometheus)

| Metric | Type | Labels | Unit | Meaning |
|---|---|---|---|---|
| `mdh_data_requests_total` | counter | `channel`, `endpoint`, `source`, `provider`, `cache_status` | requests | successful (2xx/304) data requests |
| `mdh_data_request_duration_seconds` | histogram | `channel`, `endpoint`, `source`, `provider` | s | total duration until response start |
| `mdh_cache_operation_duration_seconds` | histogram | `endpoint`, `operation`, `status` | s | one Redis response-cache operation |
| `mdh_db_operation_duration_seconds` | histogram | `endpoint`, `operation`, `status` | s | one PostgreSQL store transaction |
| `mdh_provider_request_duration_seconds` | histogram | `provider`, `operation`, `status` | s | one outermost provider call incl. pacing, budget, retries |
| `mdh_cache_concurrent_miss_total` | counter | `endpoint` | misses | miss while another miss of the same key was in flight (per replica) |
| `mdh_provider_upstream_requests_total` (existing) | counter | `provider` | attempts | HTTP attempts of metered providers |
| `mdh_provider_rate_limits_total` (existing) | counter | `provider` | responses | HTTP 429 from a provider |

Histogram buckets (all four new histograms): `0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, +Inf`.

### 4.2 Label values

| Label | Values |
|---|---|
| `channel` | `http`, `mcp` |
| `endpoint` | `prices:history`, `prices:last`, `options:chain`, `options:quote`, `market-status`, `companies:profile`, `companies:search`, `companies:news`, `companies:earnings`, `volatility:snapshot`, `volatility:history`, `volatility:stats`, `earnings:calendar`, `earnings:next`, `other` |
| `source` | `redis`, `postgres`, `provider`, `postgres+provider` |
| `cache_status` | `hit`, `miss`, `bypass` |
| `provider` | `ibkr`, `ibkrweb`, `lseg`, `finnhub`, `polygon`, `prixe`, `schwab`, `alphavantage`, `financialdatasets`, `earningsapi`, `multiple`, `none` |
| `operation` (cache, db) | `read`, `write` |
| `status` (cache, db) | `ok`, `error` |
| `operation` (provider) | `get_historical_prices`, `get_last_price`, `get_market_status`, `get_company_profile`, `search_companies`, `get_option_chain`, `get_option_quote`, `get_company_news`, `get_upcoming_earnings`, `get_symbol_earnings`, `get_earnings_for_date`, `get_earnings_history`, `get_implied_volatility`, `get_implied_volatility_history`, `other` |
| `status` (provider) | `success`, `not_found`, `timeout`, `error` |

### 4.3 Log events (Loki)

Stream selector: variable `$loki_selector`. Each line is one JSON object written by structlog to stdout; the collector must ship the line unchanged and must not turn `symbol`, `request_id` or `endpoint` into stream labels.

| Key | Type | Values / meaning |
|---|---|---|
| `event` | string | `request_completed` (HTTP), `mcp_tool_completed` (MCP) |
| `timestamp` | string | ISO 8601 UTC |
| `level` | string | `info`, `warning`, `error` |
| `request_id` | string | `X-Request-ID` for HTTP, generated per MCP tool call |
| `channel` | string | `http`, `mcp` |
| `endpoint` | string | route key (4.2) |
| `path` | string | route template (HTTP only) |
| `tool` | string | MCP tool name (MCP only) |
| `symbol` | string or null | canonical symbol of the path, null for list routes |
| `provider` | string | requested / effective provider |
| `data_provider` | string or null | provider whose data was returned (`a+b` for composed earnings); null if unknown |
| `data_source` | string or null | `redis`, `postgres`, `provider`, `postgres+provider`; null for failures |
| `cache_status` | string | `hit`, `miss`, `bypass` |
| `ttl_seconds` | number or null | effective TTL on miss, remaining TTL on hit, null on bypass |
| `redis_ms`, `db_ms`, `provider_ms` | number | wall-clock union per layer, `0` if unused |
| `total_ms` | number | until response start (= `Server-Timing` total) |
| `duration_ms` | number | until last body byte (HTTP only, existing) |
| `status_code` | number | HTTP status (HTTP only) |
| `status` | string | `ok`, `error` (MCP only) |

### 4.4 Reading notes

- `X-FastAPI-Cache: MISS` with `cache_status="bypass"` is expected for `Cache-Control: no-cache`, TTL 0 on a fresh response, and Redis cooldown; panels use the metric, not the header. A previously cached entry can still HIT after its policy is set to TTL 0.
- For `earnings:next`, the provider dimension is the upcoming provider, even when PostgreSQL supplies optional history from a second provider.
- A provider answer with ~0 ms provider time can come from a provider-internal cache (LSEG quote cache, IBKR contract cache).
- `mdh_cache_concurrent_miss_total` is per replica; the ratio in A7 is the decision basis for request coalescing.

## 5. Panels

Common matcher used below (replace literally): `F` = `channel=~"$channel", endpoint=~"$endpoint", provider=~"$provider"`. The queries below are written out in full. Prometheus range queries use `$__rate_interval`; panels marked *instant* set `instant: true, range: false` and use `$__range`. Ratios divide by zero when there is no traffic; set the value mapping `NaN` → `–` on every ratio panel. Grid: 24 columns; `gridPos` sizes are given as `w×h`.

### Row A — Overview (collapsed: no)

**A1 Data requests / s** — `stat`, 4×4, unit `reqps`, decimals 2, color mode `none`, graph mode `area`.
```promql
sum(rate(mdh_data_requests_total{channel=~"$channel", endpoint=~"$endpoint", provider=~"$provider", source=~"$source"}[$__rate_interval]))
```

**A2 Redis hit ratio** — `stat`, 4×4, *instant*, unit `percentunit`, decimals 1, thresholds: base `red`, `0.5` `orange`, `0.8` `green`.
```promql
sum(increase(mdh_data_requests_total{channel=~"$channel", endpoint=~"$endpoint", provider=~"$provider", source="redis"}[$__range])) / sum(increase(mdh_data_requests_total{channel=~"$channel", endpoint=~"$endpoint", provider=~"$provider"}[$__range]))
```

**A3 PostgreSQL share (store only)** — `stat`, 4×4, *instant*, unit `percentunit`, decimals 1, fixed color `blue`.
```promql
sum(increase(mdh_data_requests_total{channel=~"$channel", endpoint=~"$endpoint", provider=~"$provider", source="postgres"}[$__range])) / sum(increase(mdh_data_requests_total{channel=~"$channel", endpoint=~"$endpoint", provider=~"$provider"}[$__range]))
```

**A4 Provider involvement** (`provider` + `postgres+provider`) — `stat`, 4×4, *instant*, unit `percentunit`, decimals 1, thresholds: base `green`, `0.3` `orange`, `0.6` `red`.
```promql
sum(increase(mdh_data_requests_total{channel=~"$channel", endpoint=~"$endpoint", provider=~"$provider", source!~"redis|postgres"}[$__range])) / sum(increase(mdh_data_requests_total{channel=~"$channel", endpoint=~"$endpoint", provider=~"$provider"}[$__range]))
```

**A5 p95 total latency** — `stat`, 4×4, *instant*, unit `s`, decimals 3, thresholds: base `green`, `0.25` `orange`, `1` `red`.
```promql
histogram_quantile(0.95, sum by (le) (rate(mdh_data_request_duration_seconds_bucket{channel=~"$channel", endpoint=~"$endpoint", provider=~"$provider", source=~"$source"}[$__range])))
```

**A6 Provider error ratio** (`error` + `timeout`) — `stat`, 2×4, *instant*, unit `percentunit`, decimals 2, thresholds: base `green`, `0.01` `orange`, `0.05` `red`.
```promql
(sum(increase(mdh_provider_request_duration_seconds_count{provider=~"$provider", status=~"error|timeout"}[$__range])) or vector(0)) / sum(increase(mdh_provider_request_duration_seconds_count{provider=~"$provider"}[$__range]))
```

**A7 Concurrent misses / misses** — `stat`, 2×4, *instant*, unit `percentunit`, decimals 1, thresholds: base `green`, `0.05` `orange`, `0.2` `red`. Description: "Share of cache misses that started while the same key was already being loaded on the replica. Above 5 % on slow endpoints → consider request coalescing."
```promql
(sum(increase(mdh_cache_concurrent_miss_total{endpoint=~"$endpoint"}[$__range])) or vector(0)) / sum(increase(mdh_data_requests_total{channel=~"$channel", endpoint=~"$endpoint", provider=~"$provider", cache_status="miss"}[$__range]))
```

### Row B — Cache & source distribution

**B1 Source share over time** — `timeseries`, 12×8, unit `percentunit`, min 0, max 1, stacking `normal`, fill opacity 60, line width 1, legend `{{source}}` as table on the right with `mean`. Fixed colors: `redis` green, `postgres` blue, `postgres+provider` purple, `provider` orange.
```promql
sum by (source) (rate(mdh_data_requests_total{channel=~"$channel", endpoint=~"$endpoint", provider=~"$provider"}[$__rate_interval])) / ignoring(source) group_left() sum(rate(mdh_data_requests_total{channel=~"$channel", endpoint=~"$endpoint", provider=~"$provider"}[$__rate_interval]))
```

**B2 Cache status rate** — `timeseries`, 12×8, unit `reqps`, stacking `normal`, fill opacity 40, legend `{{cache_status}}`. Colors: `hit` green, `miss` orange, `bypass` grey.
```promql
sum by (cache_status) (rate(mdh_data_requests_total{channel=~"$channel", endpoint=~"$endpoint", provider=~"$provider"}[$__rate_interval]))
```

**B3 Source share per endpoint** — `table`, 12×9, *instant*, format `table`, unit `percentunit`, decimals 1. Transformations: `groupingToMatrix` (`columnField: source`, `rowField: endpoint`, `valueField: Value`), then `organize` (column order `endpoint`, `redis`, `postgres`, `postgres+provider`, `provider`). Cell type `color-background` (gradient), thresholds: base `transparent`, `0.5` `light-green`, `0.8` `green` for the `redis` column only (field override); other columns plain.
```promql
sum by (endpoint, source) (increase(mdh_data_requests_total{channel=~"$channel", endpoint=~"$endpoint", provider=~"$provider"}[$__range])) / ignoring(source) group_left() sum by (endpoint) (increase(mdh_data_requests_total{channel=~"$channel", endpoint=~"$endpoint", provider=~"$provider"}[$__range]))
```

**B4 Redis hit ratio per endpoint** — `bargauge`, 12×9, *instant*, orientation `horizontal`, display mode `gradient`, unit `percentunit`, min 0, max 1, legend `{{endpoint}}`, sort descending, thresholds: base `red`, `0.5` `orange`, `0.8` `green`.
```promql
(sum by (endpoint) (increase(mdh_data_requests_total{channel=~"$channel", endpoint=~"$endpoint", provider=~"$provider", source="redis"}[$__range])) or 0 * sum by (endpoint) (increase(mdh_data_requests_total{channel=~"$channel", endpoint=~"$endpoint", provider=~"$provider"}[$__range]))) / sum by (endpoint) (increase(mdh_data_requests_total{channel=~"$channel", endpoint=~"$endpoint", provider=~"$provider"}[$__range]))
```

**B5 Requests by endpoint and source** — `table`, 24×8, *instant*, format `table`, unit `short`, decimals 0. Transformations: `groupingToMatrix` (`columnField: source`, `rowField: endpoint`, `valueField: Value`), `calculateField` (mode `reduceRow`, reducer `sum`, alias `total`), sort by `total` descending.
```promql
sum by (endpoint, source) (increase(mdh_data_requests_total{channel=~"$channel", endpoint=~"$endpoint", provider=~"$provider"}[$__range]))
```

### Row C — Latency by data source (Redis vs PostgreSQL vs provider)

**C1 p50 by source**, **C2 p95 by source**, **C3 p99 by source** — three `timeseries`, 8×8 each, unit `s`, Y axis log scale (base 10), legend `{{source}}`, same fixed colors as B1, thresholds shown as dashed lines: `0.25` orange, `1` red. Queries in panel order:
```promql
histogram_quantile(0.5, sum by (le, source) (rate(mdh_data_request_duration_seconds_bucket{channel=~"$channel", endpoint=~"$endpoint", provider=~"$provider", source=~"$source"}[$__rate_interval])))
```
```promql
histogram_quantile(0.95, sum by (le, source) (rate(mdh_data_request_duration_seconds_bucket{channel=~"$channel", endpoint=~"$endpoint", provider=~"$provider", source=~"$source"}[$__rate_interval])))
```
```promql
histogram_quantile(0.99, sum by (le, source) (rate(mdh_data_request_duration_seconds_bucket{channel=~"$channel", endpoint=~"$endpoint", provider=~"$provider", source=~"$source"}[$__rate_interval])))
```

**C4 Percentiles by source** — `table`, 10×8, *instant*, three targets (refIds `A` p50, `B` p95, `C` p99), format `table`, unit `s`, decimals 3. Transformations: `merge`, `organize` (hide `Time`; rename `Value #A` → `p50`, `Value #B` → `p95`, `Value #C` → `p99`). Cell type `color-text` with thresholds base `green`, `0.25` `orange`, `1` `red`.
```promql
histogram_quantile(0.5, sum by (le, source) (rate(mdh_data_request_duration_seconds_bucket{channel=~"$channel", endpoint=~"$endpoint", provider=~"$provider", source=~"$source"}[$__range])))
```
```promql
histogram_quantile(0.95, sum by (le, source) (rate(mdh_data_request_duration_seconds_bucket{channel=~"$channel", endpoint=~"$endpoint", provider=~"$provider", source=~"$source"}[$__range])))
```
```promql
histogram_quantile(0.99, sum by (le, source) (rate(mdh_data_request_duration_seconds_bucket{channel=~"$channel", endpoint=~"$endpoint", provider=~"$provider", source=~"$source"}[$__range])))
```

**C5 p95 by endpoint and source** — `bargauge`, 14×8, *instant*, orientation `horizontal`, display mode `gradient`, unit `s`, legend `{{endpoint}} · {{source}}`, sort descending, thresholds base `green`, `0.25` `orange`, `1` `red`.
```promql
histogram_quantile(0.95, sum by (le, endpoint, source) (rate(mdh_data_request_duration_seconds_bucket{channel=~"$channel", endpoint=~"$endpoint", provider=~"$provider", source=~"$source"}[$__range])))
```

### Row D — Redis and PostgreSQL operations

**D1 Redis operation latency** — `timeseries`, 9×8, unit `s`, Y log scale, three targets: `A` (0.5, legend `p50 {{operation}}`), `B` (0.95, legend `p95 {{operation}}`), `C` (0.99, legend `p99 {{operation}}`):
```promql
histogram_quantile(0.5, sum by (le, operation) (rate(mdh_cache_operation_duration_seconds_bucket{endpoint=~"$endpoint", status="ok"}[$__rate_interval])))
```
```promql
histogram_quantile(0.95, sum by (le, operation) (rate(mdh_cache_operation_duration_seconds_bucket{endpoint=~"$endpoint", status="ok"}[$__rate_interval])))
```
```promql
histogram_quantile(0.99, sum by (le, operation) (rate(mdh_cache_operation_duration_seconds_bucket{endpoint=~"$endpoint", status="ok"}[$__rate_interval])))
```

**D2 PostgreSQL transaction latency** — `timeseries`, 9×8, unit `s`, Y log scale, targets `A`/`B`/`C` as D1:
```promql
histogram_quantile(0.5, sum by (le, operation) (rate(mdh_db_operation_duration_seconds_bucket{endpoint=~"$endpoint", status="ok"}[$__rate_interval])))
```
```promql
histogram_quantile(0.95, sum by (le, operation) (rate(mdh_db_operation_duration_seconds_bucket{endpoint=~"$endpoint", status="ok"}[$__rate_interval])))
```
```promql
histogram_quantile(0.99, sum by (le, operation) (rate(mdh_db_operation_duration_seconds_bucket{endpoint=~"$endpoint", status="ok"}[$__rate_interval])))
```

**D3 Redis error ratio** — `stat`, 6×4, *instant*, unit `percentunit`, decimals 2, thresholds base `green`, `0.001` `orange`, `0.01` `red`.
```promql
(sum(increase(mdh_cache_operation_duration_seconds_count{endpoint=~"$endpoint", status="error"}[$__range])) or vector(0)) / sum(increase(mdh_cache_operation_duration_seconds_count{endpoint=~"$endpoint"}[$__range]))
```

**D4 PostgreSQL error ratio** — `stat`, 6×4, *instant*, unit `percentunit`, decimals 2, thresholds as D3.
```promql
(sum(increase(mdh_db_operation_duration_seconds_count{endpoint=~"$endpoint", status="error"}[$__range])) or vector(0)) / sum(increase(mdh_db_operation_duration_seconds_count{endpoint=~"$endpoint"}[$__range]))
```

**D5 PostgreSQL p95 by endpoint** — `bargauge`, 6×8 (row layout: D1, D2, D5 side by side; D3 and D4 in a 6×8 column stacked as 6×4 each), *instant*, horizontal, unit `s`, legend `{{endpoint}} {{operation}}`, thresholds base `green`, `0.05` `orange`, `0.25` `red`.
```promql
histogram_quantile(0.95, sum by (le, endpoint, operation) (rate(mdh_db_operation_duration_seconds_bucket{endpoint=~"$endpoint", status="ok"}[$__range])))
```

### Row E — Provider latency and errors

**E1 Provider p95 (successful calls)** — `timeseries`, 12×8, unit `s`, Y log scale, legend `{{provider}}`, threshold lines `1` orange, `5` red.
```promql
histogram_quantile(0.95, sum by (le, provider) (rate(mdh_provider_request_duration_seconds_bucket{provider=~"$provider", status="success"}[$__rate_interval])))
```

**E2 Provider error ratio** — `timeseries`, 12×8, unit `percentunit`, min 0, legend `{{provider}}`, threshold lines `0.01` orange, `0.05` red.
```promql
(sum by (provider) (rate(mdh_provider_request_duration_seconds_count{provider=~"$provider", status=~"error|timeout"}[$__rate_interval])) or 0 * sum by (provider) (rate(mdh_provider_request_duration_seconds_count{provider=~"$provider"}[$__rate_interval]))) / sum by (provider) (rate(mdh_provider_request_duration_seconds_count{provider=~"$provider"}[$__rate_interval]))
```

**E3 Provider summary** — `table`, 14×8, *instant*, format `table`, five targets joined by `provider`. Transformations: `merge`, `organize` (hide `Time`; rename `Value #A` → `calls`, `Value #B` → `p50`, `Value #C` → `p95`, `Value #D` → `p99`, `Value #E` → `error ratio`). Overrides: `calls` unit `short` decimals 0; `p50`/`p95`/`p99` unit `s` decimals 3, cell `color-text`, thresholds base `green`, `1` `orange`, `5` `red`; `error ratio` unit `percentunit`, cell `color-background`, thresholds base `green`, `0.01` `orange`, `0.05` `red`.
```promql
sum by (provider) (increase(mdh_provider_request_duration_seconds_count{provider=~"$provider"}[$__range]))
```
```promql
histogram_quantile(0.5, sum by (le, provider) (rate(mdh_provider_request_duration_seconds_bucket{provider=~"$provider", status="success"}[$__range])))
```
```promql
histogram_quantile(0.95, sum by (le, provider) (rate(mdh_provider_request_duration_seconds_bucket{provider=~"$provider", status="success"}[$__range])))
```
```promql
histogram_quantile(0.99, sum by (le, provider) (rate(mdh_provider_request_duration_seconds_bucket{provider=~"$provider", status="success"}[$__range])))
```
```promql
(sum by (provider) (increase(mdh_provider_request_duration_seconds_count{provider=~"$provider", status=~"error|timeout"}[$__range])) or 0 * sum by (provider) (increase(mdh_provider_request_duration_seconds_count{provider=~"$provider"}[$__range]))) / sum by (provider) (increase(mdh_provider_request_duration_seconds_count{provider=~"$provider"}[$__range]))
```

**E4 p95 by provider and operation** — `bargauge`, 10×8, *instant*, horizontal, unit `s`, legend `{{provider}} · {{operation}}`, sort descending, thresholds base `green`, `1` `orange`, `5` `red`.
```promql
histogram_quantile(0.95, sum by (le, provider, operation) (rate(mdh_provider_request_duration_seconds_bucket{provider=~"$provider", status="success"}[$__range])))
```

**E5 Provider calls by status** — `timeseries`, 12×8, unit `reqps`, stacking `normal`, legend `{{provider}} {{status}}`. Colors by regex override: `.*success` green, `.*not_found` blue, `.*timeout` orange, `.*error` red.
```promql
sum by (provider, status) (rate(mdh_provider_request_duration_seconds_count{provider=~"$provider"}[$__rate_interval]))
```

**E6 Upstream attempts and HTTP 429** — `timeseries`, 12×8, unit `reqps`, two targets: `A` legend `attempts {{provider}}`, `B` legend `429 {{provider}}` (override: draw as bars, color red, right Y axis).
```promql
sum by (provider) (rate(mdh_provider_upstream_requests_total{provider=~"$provider"}[$__rate_interval]))
```
```promql
sum by (provider) (rate(mdh_provider_rate_limits_total{provider=~"$provider"}[$__rate_interval]))
```

### Row F — Loki: slow symbols and request detail

All Loki panels use datasource `DS_LOKI`. `$loki_selector` is interpolated verbatim.

**F1 Slowest symbols on cache miss (avg total)** — `table`, 12×9, *instant* (`queryType: instant`), unit `ms`, decimals 0. Transformations: `labelsToFields`, `sortBy` `Value` descending, `organize` (rename `Value` → `avg total_ms`). Cell `color-background` with thresholds base `green`, `500` `orange`, `2000` `red`.
```logql
topk(15, avg_over_time($loki_selector | json | event=~"request_completed|mcp_tool_completed" | channel=~"$channel" | endpoint=~"$endpoint" | data_provider=~"$provider" | cache_status="miss" | symbol!="" | unwrap total_ms | __error__="" [$__range]) by (symbol, endpoint))
```

**F2 Slowest symbols by provider time (p95)** — `table`, 12×9, *instant*, unit `ms`, decimals 0, transformations as F1 (rename `Value` → `p95 provider_ms`).
```logql
topk(15, quantile_over_time(0.95, $loki_selector | json | event=~"request_completed|mcp_tool_completed" | channel=~"$channel" | endpoint=~"$endpoint" | data_provider=~"$provider" | provider_ms > 0 | symbol!="" | unwrap provider_ms | __error__="" [$__range]) by (symbol, data_provider))
```

**F3 p95 total by data source (logs)** — `timeseries`, 12×8, unit `ms`, legend `{{data_source}}`, colors as B1. Cross-check for C2 from logs.
```logql
quantile_over_time(0.95, $loki_selector | json | event=~"request_completed|mcp_tool_completed" | channel=~"$channel" | endpoint=~"$endpoint" | data_source!="" | unwrap total_ms | __error__="" [$__interval]) by (data_source)
```

**F4 Cache misses per symbol** — `bargauge`, 12×8, *instant*, horizontal, unit `short`, legend `{{symbol}}`, sort descending, limit 15 (via `topk`).
```logql
topk(15, sum by (symbol) (count_over_time($loki_selector | json | event=~"request_completed|mcp_tool_completed" | channel=~"$channel" | endpoint=~"$endpoint" | cache_status="miss" | symbol!="" [$__range])))
```

**F5 Slow requests (detail)** — `table`, 24×10, logs query (`queryType: range`), max lines 500. Transformations: `extractFields` (source `Line`, format `json`), `organize` keeping and ordering `Time`, `request_id`, `channel`, `endpoint`, `symbol`, `data_source`, `data_provider`, `cache_status`, `ttl_seconds`, `redis_ms`, `db_ms`, `provider_ms`, `total_ms`; hide all other fields. Overrides: the four `*_ms` columns unit `ms`, decimals 1, cell `color-text`, thresholds base `green`, `250` `orange`, `1000` `red`; `ttl_seconds` unit `s`.
```logql
$loki_selector | json | event=~"request_completed|mcp_tool_completed" | channel=~"$channel" | endpoint=~"$endpoint" | data_provider=~"$provider" | symbol=~"$symbol" | total_ms >= $slow_ms
```

**F6 Request log** — `logs`, 24×10, show time, wrap lines, prettify JSON, sort descending, dedup `none`.
```logql
$loki_selector | json | event=~"request_completed|mcp_tool_completed" | channel=~"$channel" | endpoint=~"$endpoint" | symbol=~"$symbol"
```

## 6. Mandatory evaluations → panels

| Evaluation | Panels |
|---|---|
| 1. Cache and source distribution (Redis vs PostgreSQL vs provider, total and per endpoint) | A2, A3, A4, B1, B2, B3, B4, B5 |
| 2. Latency comparison p50/p95/p99, Redis vs PostgreSQL vs provider | A5, C1–C5, D1, D2 |
| 3. Pure provider latency and error ratio per provider | A6, E1–E6 |
| 4. Loki: slowest symbols on cache miss and detail table with `redis_ms`, `db_ms`, `provider_ms`, `total_ms` | F1–F6 |
| Coalescing decision basis | A7 |

## 7. Query validation

Before archiving the change (task 7.3), validate PromQL with `promtool`, LogQL log queries with `logcli query --stdin`, and LogQL metric queries (F1–F4) against a local Loki. Stdin mode accepts only log queries. Substitute Grafana variables with sample values (`$channel`, `$endpoint`, `$provider`, `$source`, `$symbol` → `.*`; `$__rate_interval`, `$__interval` → `5m`; `$__range` → `1h`; `$loki_selector` → `{app="market-data-hub"}`; `$slow_ms` → `500`).

### Check of 2026-11-20 (specification draft)

- PromQL: all 39 queries pass `promtool check rules` (Prometheus `latest`). A `promtool test rules` run with synthetic series confirmed the vector matching and expected values of A2, A4, A6, A7, B1, B3, B4, E2 and E3 (error ratio): E2 differed only in the 17th significant digit.
- LogQL: F5 and F6 executed with `logcli query --stdin` against sample `request_completed` lines (numeric filter `total_ms >= 500` correct). F1–F4 executed against a local Loki (`grafana/loki:latest`): results grouped by `symbol`/`endpoint`, `data_provider` and `data_source` as intended, lines with `symbol: null` excluded.

### Implementation check (2026-11-20)

- `promtool check rules` (Prometheus 3.16.0) accepted all 39 PromQL expressions after substituting the sample variables above.
- Captured 13 `request_completed` JSON lines from `tests/unit/test_data_observability.py`. F5 and F6 ran in `logcli query --stdin` using its `{source="stdin"}` stream: F5 correctly returned no lines at `500 ms`; F6 returned all 13.
- F1–F4 ran as `logcli instant-query` requests against a disposable local Loki with those same lines. They returned the expected symbol, endpoint, and provider groupings, including all four data sources in F3.
