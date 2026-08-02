# observability-metrics Specification

## Purpose
TBD - created by archiving change add-observability-metrics. Update Purpose after archive.
## Requirements
### Requirement: Prometheus metrics endpoint
The system SHALL expose a `/metrics` endpoint that returns Prometheus text exposition format with request metrics.

#### Scenario: Metrics endpoint returns valid Prometheus format
- **WHEN** GET request is made to `/metrics`
- **THEN** response has Content-Type `text/plain; version=0.0.4` and body contains valid Prometheus metrics

#### Scenario: Metrics available immediately
- **WHEN** service starts and no requests have been made
- **THEN** `/metrics` returns zero values for all metric series

### Requirement: Request count metric
The system SHALL track total HTTP requests with a counter metric named `mdh_http_requests_total`.

#### Scenario: Request count increments
- **WHEN** any API request completes
- **THEN** `mdh_http_requests_total` counter increments by 1 for the corresponding label combination

#### Scenario: Each label combination tracked separately
- **WHEN** requests are made to different providers/endpoints
- **THEN** each unique combination of provider, endpoint, and status_class has its own counter

### Requirement: Request duration metric
The system SHALL track HTTP request duration with a histogram metric named `mdh_http_request_duration_seconds`.

#### Scenario: Duration measured accurately
- **WHEN** a request takes 100ms to complete
- **THEN** the histogram records 0.1 seconds in the appropriate bucket

#### Scenario: Histogram buckets cover expected range
- **WHEN** requests have varying latencies from 10ms to 10s
- **THEN** histogram buckets (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0) capture the distribution

### Requirement: Low cardinality labels
The system SHALL use only three labels for metrics: provider, endpoint, and status_class with predefined values.

#### Scenario: Provider label values bounded
- **WHEN** metrics are collected
- **THEN** provider label only contains values: ibkr, lseg, finnhub, polygon, prixe, schwab, none

#### Scenario: Endpoint label values bounded
- **WHEN** metrics are collected
- **THEN** endpoint label only contains values: prices, options, news, companies, health, admin, mcp, metrics, other

#### Scenario: Status class groups HTTP codes
- **WHEN** responses have status codes 200, 201, 400, 401, 500, 503
- **THEN** status_class label contains only: 2xx, 4xx, 5xx

### Requirement: No high cardinality data in metrics
The system SHALL NOT include ticker symbols, client IDs, or request parameters in metric labels.

#### Scenario: Ticker symbols excluded from metrics
- **WHEN** request is made for /prices/AAPL/last
- **THEN** metrics do not contain "AAPL" in any label value

#### Scenario: Client identifiers excluded from metrics
- **WHEN** request includes X-Client-ID header
- **THEN** metrics do not contain the client ID value in any label

