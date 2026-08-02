## 1. Base Provider Interface

- [x] 1.1 Add abstract `test_connection()` method to `BasePriceProvider` in `app/providers/base.py`
- [x] 1.2 Add abstract `test_connection()` method to `BaseCompanyProvider` in `app/providers/base.py`
- [x] 1.3 Add abstract `test_connection()` method to `BaseOptionsProvider` in `app/providers/base.py`
- [x] 1.4 Add abstract `test_connection()` method to `BaseNewsProvider` in `app/providers/base.py`
- [x] 1.5 Document return type (dict with status_code, success, message, details) in docstrings

## 2. IBKR Provider Implementation

- [x] 2.1 Implement `test_connection()` in `app/providers/ibkr.py`
- [x] 2.2 Use `ib.isConnected()` to check existing connection or attempt `ib.connect()` with timeout
- [x] 2.3 Handle success case: return status_code 200, success True, message "Connected to IBKR"
- [x] 2.4 Handle TWS/Gateway not running: return status_code 503, success False, message "IBKR TWS/Gateway not reachable"
- [x] 2.5 Handle authentication failure: return status_code 401, success False, message "Authentication failed"

## 3. LSEG Provider Implementation

- [x] 3.1 Implement `test_connection()` in `app/providers/lseg.py`
- [x] 3.2 Open session via `refinitiv.data.open_session()` and make lightweight request (e.g., Definition for "AAPL.O")
- [x] 3.3 Close session immediately after test completes
- [x] 3.4 Handle success: return status_code 200, success True, message "LSEG session active"
- [x] 3.5 Handle invalid credentials: return status_code 401, success False, message "LSEG authentication failed"
- [x] 3.6 Handle service unavailable: return status_code 503, success False, message "LSEG service unavailable"

## 4. Finnhub Provider Implementation

- [x] 4.1 Implement `test_connection()` in `app/providers/finnhub.py`
- [x] 4.2 Make GET request to lightweight endpoint (e.g., `/quote?symbol=AAPL`) with API key
- [x] 4.3 Handle 200 OK: return status_code 200, success True, message "Finnhub API key valid"
- [x] 4.4 Handle 401/403: return status_code 401, success False, message "Invalid Finnhub API key"
- [x] 4.5 Handle 5xx/timeout: return status_code 503, success False, message "Finnhub service unavailable"

## 5. Schwab Provider Implementation

- [x] 5.1 Implement `test_connection()` in `app/providers/schwab.py`
- [x] 5.2 Call lightweight endpoint (e.g., `/accounts` or `/userPreference`) to validate OAuth token
- [x] 5.3 Handle success: return status_code 200, success True, message "Schwab OAuth token valid"
- [x] 5.4 Handle 401: return status_code 401, success False, message "Schwab OAuth token expired or invalid"
- [x] 5.5 Handle service error: return status_code 503, success False, message "Schwab service unavailable"

## 6. Polygon Provider Implementation

- [x] 6.1 Implement `test_connection()` in `app/providers/polygon.py`
- [x] 6.2 Make GET request to lightweight endpoint with API key (e.g., `/v2/aggs/ticker/AAPL/prev`)
- [x] 6.3 Handle success: return status_code 200, success True, message "Polygon API key valid"
- [x] 6.4 Handle 401/403: return status_code 401, success False, message "Invalid Polygon API key"
- [x] 6.5 Handle service error: return status_code 503, success False, message "Polygon service unavailable"

## 7. Prixe Provider Implementation

- [x] 7.1 Implement `test_connection()` in `app/providers/prixe.py`
- [x] 7.2 Make GET request to lightweight endpoint with API key
- [x] 7.3 Handle success: return status_code 200, success True, message "Prixe API key valid"
- [x] 7.4 Handle 401/403: return status_code 401, success False, message "Invalid Prixe API key"
- [x] 7.5 Handle service error: return status_code 503, success False, message "Prixe service unavailable"

## 8. API Endpoint

- [x] 8.1 Add `POST /admin/test-connection/{provider}` endpoint to `app/api/routes_admin.py`
- [x] 8.2 Validate provider name against registry (return 404 if invalid or not enabled)
- [x] 8.3 Call provider's `test_connection()` method and return result as JSON
- [x] 8.4 Add authentication check (require admin auth middleware)
- [x] 8.5 Add error handling for exceptions during test (return 500 with error details)
- [x] 8.6 Log failures at WARNING level with provider name, status_code, and error message

## 9. Response Models

- [x] 9.1 Create Pydantic model `ConnectionTestResult` in `app/models/` with fields: status_code, success, message, details
- [x] 9.2 Use `ConnectionTestResult` as response_model for API endpoint
- [x] 9.3 Add OpenAPI documentation for endpoint with example responses (200 success, 401 auth failed, 503 unavailable)

## 10. Timeout Handling

- [x] 10.1 Wrap all `test_connection()` calls in `asyncio.wait_for()` with 10-second timeout
- [x] 10.2 On timeout, return status_code 503, success False, message "Connection test timeout"
- [x] 10.3 Test timeout behavior with simulated slow provider

## 11. UI Integration

- [x] 11.1 Add "Test Connection" button next to each provider API key input in admin panel template
- [x] 11.2 Add JavaScript handler to send POST request to `/admin/test-connection/{provider}` on button click
- [x] 11.3 Display loading state while test is in progress
- [x] 11.4 Display result inline: green message for success (status 200), red for failure (401/503), yellow for warnings
- [x] 11.5 Show status_code prominently alongside message
- [x] 11.6 Add expandable details section to show provider-specific details dict
- [x] 11.7 Add CSS styling for success/failure/warning color-coding

## 12. Testing

- [x] 12.1 Write unit tests for each provider's `test_connection()` with mocked success/failure scenarios
- [x] 12.2 Write API endpoint test for valid provider (mock `test_connection()` call)
- [x] 12.3 Write API endpoint test for invalid provider name (404 expected)
- [x] 12.4 Write API endpoint test for unauthenticated request (401 expected)
- [x] 12.5 Write timeout test to verify 10-second limit
- [x] 12.6 Manually test UI button and result display for all providers

## 13. Documentation

- [x] 13.1 Add docstrings to `test_connection()` abstract methods in base classes
- [x] 13.2 Document expected response times per provider in design doc or README
- [x] 13.3 Document quota/rate limit implications for REST providers (Finnhub, Polygon, Schwab, Prixe)
- [x] 13.4 Update OpenAPI spec with new endpoint (run `openapi-sync` skill after implementation)

## 14. Deployment

- [x] 14.1 Run lint check (`uv run ruff check app/`)
