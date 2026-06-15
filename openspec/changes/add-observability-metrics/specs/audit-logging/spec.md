## ADDED Requirements

### Requirement: Structured JSON audit logs
The system SHALL emit one structured JSON log entry to stdout for each completed HTTP request.

#### Scenario: Each request produces one log entry
- **WHEN** an HTTP request completes
- **THEN** exactly one JSON log line is written to stdout with event "request_completed"

#### Scenario: JSON format is valid
- **WHEN** audit log is emitted
- **THEN** each line is valid JSON that can be parsed by standard tools

### Requirement: Required audit log fields
Each audit log entry SHALL contain: timestamp, client_id, method, path, provider, params, status_code, duration_ms, and level fields.

#### Scenario: All required fields present
- **WHEN** GET /prices/AAPL/last?provider=lseg completes with status 200
- **THEN** log contains all required fields with appropriate values

#### Scenario: Timestamp in ISO 8601 format
- **WHEN** request completes at 2:32:01.123456 PM UTC on June 15, 2026
- **THEN** timestamp field contains "2026-06-15T14:32:01.123456Z"

#### Scenario: Duration measured in milliseconds
- **WHEN** request takes 87.42 milliseconds
- **THEN** duration_ms field contains 87.42

### Requirement: Client identification
The system SHALL extract client_id from X-Client-ID header or auth token, defaulting to "anonymous" if absent.

#### Scenario: Client ID from header
- **WHEN** request includes header "X-Client-ID: trading-bot-7"
- **THEN** audit log contains client_id: "trading-bot-7"

#### Scenario: Anonymous when no identification
- **WHEN** request has no X-Client-ID header or auth token
- **THEN** audit log contains client_id: "anonymous"

### Requirement: Path uses route template
The system SHALL log the route template pattern, not the resolved URL path.

#### Scenario: Path parameters replaced with template
- **WHEN** request is made to /prices/AAPL/last
- **THEN** path field contains "/prices/{symbol}/last"

#### Scenario: Query parameters captured separately
- **WHEN** request includes query string ?provider=lseg&interval=1m
- **THEN** params field contains {"provider": "lseg", "interval": "1m"}

### Requirement: Log level based on status
The system SHALL set log level to "info" for 2xx/3xx, "warning" for 4xx, and "error" for 5xx responses.

#### Scenario: Success responses logged as info
- **WHEN** response status is 200 or 301
- **THEN** log level is "info"

#### Scenario: Client errors logged as warning
- **WHEN** response status is 400, 401, 403, or 404
- **THEN** log level is "warning"

#### Scenario: Server errors logged as error
- **WHEN** response status is 500, 502, or 503
- **THEN** log level is "error"

### Requirement: Exclude response payloads
The system SHALL NOT include response bodies or market data in audit logs.

#### Scenario: Price data not logged
- **WHEN** response contains {"symbol": "AAPL", "price": 150.25}
- **THEN** audit log does not contain this price data

#### Scenario: Large responses don't affect log size
- **WHEN** response is 1MB option chain
- **THEN** audit log entry remains under 1KB

### Requirement: Skip certain endpoints
The system SHALL NOT emit audit logs for /health, /metrics, /docs, /redoc, /openapi.json, or /admin paths.

#### Scenario: Health checks not logged
- **WHEN** GET /health request completes
- **THEN** no audit log entry is created

#### Scenario: Metrics endpoint not logged
- **WHEN** GET /metrics request completes
- **THEN** no audit log entry is created to avoid recursion