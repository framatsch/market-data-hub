# data-source-observability Specification

## Purpose
Per-request data-source and layer timing observability (Redis response cache, PostgreSQL history store, upstream provider) exposed via HTTP headers (`Server-Timing`, `X-Data-Source`, `X-Data-Provider`, `X-Request-ID`), Prometheus metrics, and structured audit log fields across HTTP and MCP.
## Requirements
### Requirement: Data routes and route keys
The system SHALL treat the following routes as data routes and identify them by these route keys in headers, metrics and logs: `GET /prices/{symbol}/history` (`prices:history`), `GET /prices/{symbol}/last` (`prices:last`), `GET /options/{symbol}/chain` (`options:chain`), `GET /options/{symbol}/quote/{option_id}` (`options:quote`), `GET /market-status` (`market-status`), `GET /companies/{symbol}` (`companies:profile`), `GET /companies/search` (`companies:search`), `GET /companies/{symbol}/news` (`companies:news`), `GET /companies/{symbol}/earnings` (`companies:earnings`), `GET /volatility/{symbol}` (`volatility:snapshot`), `GET /volatility/{symbol}/history` (`volatility:history`), `GET /volatility/{symbol}/stats` (`volatility:stats`), `GET /earnings/calendar` (`earnings:calendar`) and `GET /earnings/next` (`earnings:next`). MCP tools SHALL map to the route key of the route they mirror (`get_last_price` → `prices:last`, `get_historical_prices` → `prices:history`, `get_option_chain` → `options:chain`, `get_option_quote` → `options:quote`, `get_company_profile` → `companies:profile`, `search_companies` → `companies:search`, `get_company_news` → `companies:news`, `get_market_status` → `market-status`, `get_implied_volatility` → `volatility:snapshot`, `get_implied_volatility_history` → `volatility:history`, `get_implied_volatility_stats` → `volatility:stats`, `get_earnings_calendar` → `earnings:calendar`, `get_next_earnings` → `earnings:next`).

#### Scenario: Route key of a history request
- **WHEN** `GET /prices/AAPL/history?interval=1d` is served
- **THEN** its headers, metrics and log line use the endpoint `prices:history`

#### Scenario: MCP tool
- **WHEN** the MCP tool `get_option_chain` is called
- **THEN** its metrics and log line use the endpoint `options:chain`

#### Scenario: Non-data route
- **WHEN** `GET /providers` or `GET /health` is served
- **THEN** no data-source headers are set and no data-request metric is recorded

### Requirement: Request telemetry context
For every data request (HTTP data route or MCP tool call) the system SHALL bind one telemetry context that collects, for the duration of the request, the time spent in Redis operations of the response cache, in PostgreSQL store transactions and in provider interface calls, together with the cache status, the store outcome and the data provider. Work started by the request in other tasks or threads SHALL record into the same context. The context SHALL NOT change response bodies.

#### Scenario: Parallel provider calls
- **WHEN** an earnings request calls the provider for three days in parallel
- **THEN** all three calls are recorded in the request's telemetry context

#### Scenario: Body unchanged
- **WHEN** the same request is served with and without this capability
- **THEN** the JSON and CSV bodies are identical

### Requirement: Layer durations
The duration of a layer (`redis`, `db`, `provider`) SHALL be the length of the union of its recorded time intervals within the request, measured on the wall clock from the start of the request until the response headers are sent. Provider intervals SHALL include pacing waits, request budget checks, retries and backoff inside the provider call. A provider interface method called from within another provider interface method SHALL be recorded once, as part of the outer call. Waiting for the store series lock SHALL NOT count to any layer.

#### Scenario: Parallel calls counted once
- **WHEN** two provider calls of one request run from 0 to 400 ms and from 100 to 500 ms
- **THEN** the provider duration of the request is 500 ms

#### Scenario: Retries included
- **WHEN** a metered provider answers the first attempt with 429 and the second after a 500 ms backoff
- **THEN** the provider duration includes the backoff

#### Scenario: Nested provider method
- **WHEN** `get_option_chain` of a provider calls its own `get_last_price`
- **THEN** one provider interval is recorded for the request

#### Scenario: Layer never exceeds total
- **WHEN** any data request is served
- **THEN** each layer duration is less than or equal to the total duration

### Requirement: Cache status
Each data request SHALL have a cache status: `hit` when the answer came from the Redis response cache (including a `304 Not Modified` revalidation), `miss` when the cache was read without an entry and the result was to be written, and `bypass` when the response cache was not used for the answer: the route is not cached, caching is disabled, Redis is in its error cooldown, the effective TTL is 0 and prevents caching a fresh response, the answer is stale, the client sent `Cache-Control: no-cache` or `no-store`, or an MCP call requested a refresh. Changing the configured TTL to 0 SHALL NOT affect existing entries, which still count as hits until expiry. The `X-FastAPI-Cache` header SHALL remain as set by the cache library.

#### Scenario: Repeated chain request
- **WHEN** `GET /options/SPX/chain` is requested twice within the TTL
- **THEN** the first request has cache status `miss` and the second `hit`

#### Scenario: Forced refresh
- **WHEN** a request carries `Cache-Control: no-cache`
- **THEN** the cache status is `bypass` and `X-FastAPI-Cache` is `MISS`

#### Scenario: Uncached route
- **WHEN** `GET /prices/AAPL/last` is served
- **THEN** the cache status is `bypass` and no `X-FastAPI-Cache` header is sent

#### Scenario: Redis down
- **WHEN** Redis is in its error cooldown and a chain is requested
- **THEN** the cache status is `bypass`

### Requirement: Data source
Each successful data response SHALL have exactly one data source: `redis` for a cache hit; for a store-backed answer `postgres` when the store answered without a provider call or served stored data after a provider failure, `postgres+provider` when stored data was completed by a provider call, and `provider` when the store held nothing for the request and all data came from the provider; `provider` for all other answers. When the store is disabled, an earnings answer read only from the earnings fallback keys in Redis SHALL have the source `redis`.

#### Scenario: Weekend daily history from the store
- **WHEN** a daily price series is covered and `GET /prices/AAPL/history?interval=1d` misses the response cache on Saturday
- **THEN** the data source is `postgres`

#### Scenario: Session with forming bar
- **WHEN** the same request is made on Wednesday 11:00 ET and the provider delivers the tail
- **THEN** the data source is `postgres+provider`

#### Scenario: First request for a series
- **WHEN** no series exists and the provider delivers the whole range
- **THEN** the data source is `provider`

#### Scenario: Provider outage
- **WHEN** stored bars are served because the provider timed out
- **THEN** the data source is `postgres`

#### Scenario: Options chain miss
- **WHEN** an option chain misses the response cache
- **THEN** the data source is `provider` and no store transaction is recorded

### Requirement: Data provider
Each successful data response SHALL name the data provider: the provider whose data the response contains. It SHALL be the effective provider of the request, the provider of the series actually served when stored data of another provider is returned (`meta.source_provider`), and both providers joined with `+` (upcoming provider first) for an earnings answer composed from two providers. On a cache hit it SHALL be determined from the cache key; for default earnings keys include only configured providers in the roles selected by `kind`.

#### Scenario: Default provider
- **WHEN** the default options provider is `schwab` and `GET /options/SPX/chain` is served
- **THEN** the data provider is `schwab`

#### Scenario: Stale fallback to another provider
- **WHEN** a `schwab` history request is answered from the stored `ibkr` series after a provider failure
- **THEN** the data provider is `ibkr`

#### Scenario: Composed earnings
- **WHEN** `GET /earnings/calendar?kind=all` composes upcoming events from `earningsapi` and reported events from `financialdatasets`
- **THEN** the data provider is `earningsapi+financialdatasets`

#### Scenario: Upcoming-only earnings cache hit
- **WHEN** `GET /earnings/calendar?kind=upcoming` hits the cache with `earningsapi` as upcoming default and `financialdatasets` as history default
- **THEN** the data provider is `earningsapi` even though the key contains both defaults

#### Scenario: Next earnings with historical enrichment
- **WHEN** `GET /earnings/next` or MCP `get_next_earnings` reports a next date from `earningsapi` and a `last_reported` event stored from `financialdatasets`
- **THEN** the data provider is `earningsapi` on both a fresh answer and a cache hit, and `last_reported.provider` still identifies `financialdatasets` in the body

### Requirement: Data-source response headers
Every successful response of an HTTP data route (JSON and CSV, status 2xx or 304) SHALL carry:
- `Server-Timing` with, in this order and each only when the layer was used, `redis;desc="<cache status>";dur=<ms>`, `db;desc="<store outcome>";dur=<ms>` with store outcome `hit`, `partial`, `miss` or `stale`, `provider;desc="<data provider>";dur=<ms>`, `redis-write;dur=<ms>`, and always `total;dur=<ms>`, where `total` is measured from request start until the response headers are sent and durations have one decimal;
- `X-Data-Source` with the data source;
- `X-Data-Provider` with the data provider.
Error responses SHALL NOT carry `X-Data-Source` and `X-Data-Provider`, and SHALL carry `Server-Timing` with `total` only.

#### Scenario: Redis hit
- **WHEN** a chain is served from the response cache in 4.2 ms with a 1.8 ms Redis read
- **THEN** `Server-Timing` is `redis;desc="hit";dur=1.8, total;dur=4.2`, `X-Data-Source` is `redis` and `X-FastAPI-Cache` is `HIT`

#### Scenario: Store hit
- **WHEN** a daily history request misses Redis and is answered from the store
- **THEN** `Server-Timing` contains `redis;desc="miss"`, `db;desc="hit"` and `total`, no `provider` entry, and `X-Data-Source` is `postgres`

#### Scenario: Provider call
- **WHEN** an option chain misses Redis and is loaded from `ibkr` and written to Redis
- **THEN** `Server-Timing` contains `redis;desc="miss"`, `provider;desc="ibkr"`, `redis-write` and `total`, no `db` entry, and `X-Data-Source` is `provider`

#### Scenario: Uncached route
- **WHEN** `GET /prices/AAPL/last` is served by `schwab`
- **THEN** `Server-Timing` has a `provider` and a `total` entry and no `redis` entry, and `X-Data-Source` is `provider`

#### Scenario: Error response
- **WHEN** a data request fails with `PROVIDER_NOT_AVAILABLE`
- **THEN** the response carries `Server-Timing` with only `total` and no `X-Data-Source`

### Requirement: Request ID
Every HTTP response SHALL carry `X-Request-ID`. When the request carries an `X-Request-ID` matching `^[A-Za-z0-9._:-]{1,128}$`, that value SHALL be used; otherwise a new random ID SHALL be generated. The ID SHALL be present in every structured log record written while the request is handled.

#### Scenario: Client-supplied ID
- **WHEN** a request carries `X-Request-ID: vt-7f3a`
- **THEN** the response carries `X-Request-ID: vt-7f3a` and the `request_completed` log line has `request_id` `vt-7f3a`

#### Scenario: Invalid ID
- **WHEN** a request carries an `X-Request-ID` containing a line break or longer than 128 characters
- **THEN** a new ID is generated and returned

#### Scenario: Error and non-data responses
- **WHEN** `GET /health` is served or a request fails with 401
- **THEN** the response carries an `X-Request-ID`

### Requirement: OpenAPI documentation of response headers
The OpenAPI document SHALL describe, for the success response of every HTTP data route, the headers `Server-Timing`, `X-Data-Source` (enum `redis`, `postgres`, `provider`, `postgres+provider`), `X-Data-Provider`, `X-FastAPI-Cache` (enum `HIT`, `MISS`; absent when the cache is not used; `MISS` also for `no-cache`, TTL 0 and Redis cooldown), `X-Request-ID` and `Cache-Control`, and for routes with CSV output `X-MDH-Data-As-Of`.

#### Scenario: Headers in the schema
- **WHEN** `GET /openapi.json` is requested
- **THEN** the `200` response of each of the 14 data routes lists the documented headers

### Requirement: CORS exposure of response headers
The CORS configuration SHALL expose `Server-Timing`, `X-FastAPI-Cache`, `X-Data-Source`, `X-Data-Provider`, `X-Request-ID` and `X-MDH-Data-As-Of` to allowed origins.

#### Scenario: Preflighted browser request
- **WHEN** a request from an allowed origin is answered
- **THEN** `Access-Control-Expose-Headers` lists the six headers

### Requirement: Data request metrics
The system SHALL record each completed data request with status 2xx or 304 in the counter `mdh_data_requests_total` with labels `channel` (`http`, `mcp`), `endpoint` (route key), `source` (data source), `provider` (data provider: one of the known provider names, `multiple` for composed answers, `none` when unknown) and `cache_status` (`hit`, `miss`, `bypass`), and its total duration in the histogram `mdh_data_request_duration_seconds` with labels `channel`, `endpoint`, `source` and `provider`. Failed data requests SHALL NOT be recorded in these two metrics.

#### Scenario: Redis hit counted
- **WHEN** an HTTP chain request for `schwab` is served from the response cache
- **THEN** `mdh_data_requests_total{channel="http",endpoint="options:chain",source="redis",provider="schwab",cache_status="hit"}` increases by 1

#### Scenario: Store answer counted
- **WHEN** an MCP `get_historical_prices` call is answered from the store
- **THEN** `mdh_data_requests_total{channel="mcp",endpoint="prices:history",source="postgres",cache_status="miss"}` increases by 1

#### Scenario: Failed request not counted
- **WHEN** a data request fails with 503
- **THEN** `mdh_data_requests_total` does not change and `mdh_http_requests_total` records the 5xx

### Requirement: Layer timing metrics
The system SHALL observe every Redis response-cache operation in `mdh_cache_operation_duration_seconds` (labels `endpoint`, `operation` `read`/`write`, `status` `ok`/`error`), every PostgreSQL store transaction in `mdh_db_operation_duration_seconds` (labels `endpoint`, `operation` `read`/`write`, `status` `ok`/`error`; a transaction that writes is `write`), and every outermost provider interface call in `mdh_provider_request_duration_seconds` (labels `provider`, `operation` = interface method name or `other`, `status` `success`/`not_found`/`timeout`/`error`). Operations outside a data request SHALL use the endpoint `other`. Cancelled provider calls SHALL NOT be observed. Connection tests and admin calls SHALL NOT be observed as provider requests.

#### Scenario: Provider timeout
- **WHEN** `get_historical_prices` of `schwab` raises a provider timeout after 10 s
- **THEN** `mdh_provider_request_duration_seconds{provider="schwab",operation="get_historical_prices",status="timeout"}` observes about 10 s

#### Scenario: Data not found
- **WHEN** a provider raises `DATA_NOT_FOUND`
- **THEN** the call is observed with `status="not_found"`

#### Scenario: Store write
- **WHEN** a tail synchronisation writes new bars
- **THEN** `mdh_db_operation_duration_seconds{endpoint="prices:history",operation="write",status="ok"}` observes the transaction

#### Scenario: Redis failure
- **WHEN** a Redis read raises a connection error
- **THEN** `mdh_cache_operation_duration_seconds{operation="read",status="error"}` observes it and the request is served live

### Requirement: Histogram buckets of data metrics
`mdh_data_request_duration_seconds`, `mdh_cache_operation_duration_seconds`, `mdh_db_operation_duration_seconds` and `mdh_provider_request_duration_seconds` SHALL use the buckets 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10 and 30 seconds.

#### Scenario: Redis read resolution
- **WHEN** a Redis read takes 1.8 ms
- **THEN** it falls into the 0.0025 s bucket

#### Scenario: Slow provider
- **WHEN** a provider call takes 12 s
- **THEN** it falls into the 30 s bucket

### Requirement: Concurrent cache miss counter
The system SHALL increase `mdh_cache_concurrent_miss_total{endpoint}` when a response-cache miss starts for a key while another miss for the same key is still being served on the same instance, for HTTP and MCP keys. It SHALL NOT change how the request is served.

#### Scenario: Two concurrent misses
- **WHEN** two requests for the same expired chain key arrive while the first one is still waiting for the provider
- **THEN** `mdh_cache_concurrent_miss_total{endpoint="options:chain"}` increases by 1 and both requests call the provider as before

#### Scenario: Sequential misses
- **WHEN** the second request arrives after the first one has finished
- **THEN** the counter does not change

### Requirement: Data request log fields
The `request_completed` audit log event of an HTTP data route SHALL contain, in addition to its existing fields, `request_id`, `channel` (`http`), `endpoint`, `symbol` (canonical symbol of the path, `null` for routes without a path symbol), `data_source`, `data_provider`, `cache_status`, `ttl_seconds` (effective TTL written on a miss, `0` when nothing was written, remaining TTL on a hit, `null` on bypass), `redis_ms`, `db_ms`, `provider_ms` and `total_ms` (numbers in milliseconds, `0` for an unused layer, `total_ms` equal to the `Server-Timing` total). Every MCP tool call SHALL emit one event `mcp_tool_completed` with the same fields, `channel` `mcp`, `tool` and `status` (`ok`, `error`). Failed data requests SHALL log the fields known at the time of failure. The log SHALL NOT contain response payloads.

#### Scenario: Slow miss findable
- **WHEN** `GET /options/NVDA/chain` misses the cache and takes 2.4 s at `ibkr`
- **THEN** the `request_completed` line contains `symbol` `NVDA`, `cache_status` `miss`, `data_source` `provider`, `data_provider` `ibkr` and `provider_ms` about 2400

#### Scenario: Hit with remaining TTL
- **WHEN** a chain cached with 900 s is read 600 s later
- **THEN** the log line has `cache_status` `hit` and `ttl_seconds` about 300

#### Scenario: MCP call
- **WHEN** the MCP tool `get_implied_volatility_stats` is called for `AAPL`
- **THEN** one `mcp_tool_completed` line with `channel` `mcp`, `endpoint` `volatility:stats`, `tool` `get_implied_volatility_stats` and `symbol` `AAPL` is written
