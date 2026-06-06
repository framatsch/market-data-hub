## 1. Base Provider Interface

- [ ] 1.1 Add abstract `test_connection()` method to `BasePriceProvider` in `app/providers/base.py`
- [ ] 1.2 Add abstract `test_connection()` method to `BaseCompanyProvider` in `app/providers/base.py`
- [ ] 1.3 Add abstract `test_connection()` method to `BaseOptionsProvider` in `app/providers/base.py`
- [ ] 1.4 Add abstract `test_connection()` method to `BaseNewsProvider` in `app/providers/base.py`
- [ ] 1.5 Document return type (dict with status_code, success, message, details) in docstrings

## 2. IBKR Provider Implementation

- [ ] 2.1 Implement `test_connection()` in `app/providers/ibkr.py`
- [ ] 2.2 Use `ib.isConnected()` to check existing connection or attempt `ib.connect()` with timeout
- [ ] 2.3 Handle success case: return status_code 200, success True, message "Connected to IBKR"
- [ ] 2.4 Handle TWS/Gateway not running: return status_code 503, success False, message "IBKR TWS/Gateway not reachable"
- [ ] 2.5 Handle authentication failure: return status_code 401, success False, message "Authentication failed"

## 3. LSEG Provider Implementation

- [ ] 3.1 Implement `test_connection()` in `app/providers/lseg.py`
- [ ] 3.2 Open session via `refinitiv.data.open_session()` and make lightweight request (e.g., Definition for "AAPL.O")
- [ ] 3.3 Close session immediately after test completes
- [ ] 3.4 Handle success: return status_code 200, success True, message "LSEG session active"
- [ ] 3.5 Handle invalid credentials: return status_code 401, success False, message "LSEG authentication failed"
- [ ] 3.6 Handle service unavailable: return status_code 503, success False, message "LSEG service unavailable"

## 4. Finnhub Provider Implementation

- [ ] 4.1 Implement `test_connection()` in `app/providers/finnhub.py`
- [ ] 4.2 Make GET request to lightweight endpoint (e.g., `/quote?symbol=AAPL`) with API key
- [ ] 4.3 Handle 200 OK: return status_code 200, success True, message "Finnhub API key valid"
- [ ] 4.4 Handle 401/403: return status_code 401, success False, message "Invalid Finnhub API key"
- [ ] 4.5 Handle 5xx/timeout: return status_code 503, success False, message "Finnhub service unavailable"

## 5. Schwab Provider Implementation

- [ ] 5.1 Implement `test_connection()` in `app/providers/schwab.py`
- [ ] 5.2 Call lightweight endpoint (e.g., `/accounts` or `/userPreference`) to validate OAuth token
- [ ] 5.3 Handle success: return status_code 200, success True, message "Schwab OAuth token valid"
- [ ] 5.4 Handle 401: return status_code 401, success False, message "Schwab OAuth token expired or invalid"
- [ ] 5.5 Handle service error: return status_code 503, success False, message "Schwab service unavailable"

## 6. Polygon Provider Implementation

- [ ] 6.1 Implement `test_connection()` in `app/providers/polygon.py`
- [ ] 6.2 Make GET request to lightweight endpoint with API key (e.g., `/v2/aggs/ticker/AAPL/prev`)
- [ ] 6.3 Handle success: return status_code 200, success True, message "Polygon API key valid"
- [ ] 6.4 Handle 401/403: return status_code 401, success False, message "Invalid Polygon API key"
- [ ] 6.5 Handle service error: return status_code 503, success False, message "Polygon service unavailable"

## 7. Prixe Provider Implementation

- [ ] 7.1 Implement `test_connection()` in `app/providers/prixe.py`
- [ ] 7.2 Make GET request to lightweight endpoint with API key
- [ ] 7.3 Handle success: return status_code 200, success True, message "Prixe API key valid"
- [ ] 7.4 Handle 401/403: return status_code 401, success False, message "Invalid Prixe API key"
- [ ] 7.5 Handle service error: return status_code 503, success False, message "Prixe service unavailable"

## 8. API Endpoint

- [ ] 8.1 Add `POST /admin/test-connection/{provider}` endpoint to `app/api/routes_admin.py`
- [ ] 8.2 Validate provider name against registry (return 404 if invalid or not enabled)
- [ ] 8.3 Call provider's `test_connection()` method and return result as JSON
- [ ] 8.4 Add authentication check (require admin auth middleware)
- [ ] 8.5 Add error handling for exceptions during test (return 500 with error details)
- [ ] 8.6 Log failures at WARNING level with provider name, status_code, and error message

## 9. Response Models

- [ ] 9.1 Create Pydantic model `ConnectionTestResult` in `app/models/` with fields: status_code, success, message, details
- [ ] 9.2 Use `ConnectionTestResult` as response_model for API endpoint
- [ ] 9.3 Add OpenAPI documentation for endpoint with example responses (200 success, 401 auth failed, 503 unavailable)

## 10. Timeout Handling

- [ ] 10.1 Wrap all `test_connection()` calls in `asyncio.wait_for()` with 10-second timeout
- [ ] 10.2 On timeout, return status_code 503, success False, message "Connection test timeout"
- [ ] 10.3 Test timeout behavior with simulated slow provider

## 11. UI Integration

- [ ] 11.1 Add "Test Connection" button next to each provider API key input in admin panel template
- [ ] 11.2 Add JavaScript handler to send POST request to `/admin/test-connection/{provider}` on button click
- [ ] 11.3 Display loading state while test is in progress
- [ ] 11.4 Display result inline: green message for success (status 200), red for failure (401/503), yellow for warnings
- [ ] 11.5 Show status_code prominently alongside message
- [ ] 11.6 Add expandable details section to show provider-specific details dict
- [ ] 11.7 Add CSS styling for success/failure/warning color-coding

## 12. Testing

- [ ] 12.1 Write unit tests for each provider's `test_connection()` with mocked success/failure scenarios
- [ ] 12.2 Write API endpoint test for valid provider (mock `test_connection()` call)
- [ ] 12.3 Write API endpoint test for invalid provider name (404 expected)
- [ ] 12.4 Write API endpoint test for unauthenticated request (401 expected)
- [ ] 12.5 Write timeout test to verify 10-second limit
- [ ] 12.6 Manually test UI button and result display for all providers

## 13. Documentation

- [ ] 13.1 Add docstrings to `test_connection()` abstract methods in base classes
- [ ] 13.2 Document expected response times per provider in design doc or README
- [ ] 13.3 Document quota/rate limit implications for REST providers (Finnhub, Polygon, Schwab, Prixe)
- [ ] 13.4 Update OpenAPI spec with new endpoint (run `openapi-sync` skill after implementation)

## 14. Deployment

- [ ] 14.1 Run lint check (`uv run ruff check app/`)
- [ ] 14.2 Run full test suite (`uv run pytest --maxfail=1 --disable-warnings`)
- [ ] 14.3 Test all providers in staging environment with real credentials
- [ ] 14.4 Deploy to production and verify endpoint accessibility
- [ ] 14.5 Monitor logs for any unexpected failures or timeout issues
