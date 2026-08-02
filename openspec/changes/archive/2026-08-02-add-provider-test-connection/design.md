## Context

Currently, the Market Data Hub supports 6 data providers (IBKR, LSEG, Finnhub, Schwab, Polygon, Prixe) that require API credentials. When credentials are invalid, expired, or misconfigured, users only discover this during actual data requests, resulting in cryptic error messages. There is no proactive way to validate credentials.

The system uses abstract base classes (`BasePriceProvider`, `BaseCompanyProvider`, `BaseOptionsProvider`, `BaseNewsProvider`) to define provider contracts. Each provider implements these interfaces with their specific client libraries (ib_async for IBKR, refinitiv.data for LSEG, httpx for REST-based providers).

## Goals / Non-Goals

**Goals:**
- Provide a lightweight connectivity test for each provider that validates credentials
- Return clear success/failure status with actionable error messages
- Add UI integration for one-click testing from the admin panel
- Ensure tests are fast (< 5 seconds) and do not consume quota/rate limits unnecessarily
- Support both synchronous (LSEG) and asynchronous (IBKR, REST providers) implementations

**Non-Goals:**
- Comprehensive provider health monitoring or automated retry logic
- Testing all provider capabilities (focus on basic connectivity only)
- Real-time connection status tracking or heartbeat mechanisms
- Provider-specific advanced diagnostics (e.g., TWS version detection for IBKR)

## Decisions

### 1. Abstract Method in Base Classes

**Decision:** Add `test_connection()` as an abstract method to each base provider class (`BasePriceProvider`, `BaseCompanyProvider`, `BaseOptionsProvider`, `BaseNewsProvider`).

**Rationale:**
- Enforces implementation across all current and future providers
- Allows polymorphic testing via the provider registry
- Keeps the contract explicit and discoverable

**Alternatives considered:**
- Optional method with default NotImplementedError: Would allow providers to skip implementation
- Separate TestableProvider mixin: Adds complexity and requires multiple inheritance
- Registry-level implementation: Would duplicate provider-specific logic outside provider classes

### 2. Test Strategy Per Provider

**IBKR:** Call `ib.connect()` or check existing connection status via `ib.isConnected()`. If already connected, return success. If not connected, attempt connection with timeout.

**LSEG:** Open a session via `refinitiv.data.open_session()` and request a lightweight instrument (e.g., `rd.content.fundamental.Definition("AAPL.O")`). Close session immediately after.

**Finnhub, Polygon, Prixe (REST):** Make a GET request to a lightweight endpoint (e.g., `/quote?symbol=AAPL` or `/status`) with the API key. Check for 200 OK vs 401/403 authentication errors.

**Schwab:** Call a lightweight endpoint like `/accounts` or `/userPreference` to validate the OAuth token. Handle 401 specifically to detect expired tokens.

**Rationale:**
- Each test uses the provider's native client library for consistency
- Tests are lightweight and avoid consuming quotas (no expensive data requests)
- Tests validate both authentication and basic connectivity

### 3. Response Format

**Decision:** Return a standardized dict from `test_connection()`:
```python
{
    "status_code": int,  # HTTP-like status: 200 = success, 401 = auth failed, 503 = service unavailable, etc.
    "success": bool,     # True if connection test passed
    "message": str,      # Human-readable message
    "details": dict      # Provider-specific details (e.g., session ID, endpoint URL)
}
```

**Rationale:**
- HTTP status codes are universally understood (200 OK, 401 Unauthorized, etc.)
- `success` boolean simplifies UI logic
- `message` provides actionable feedback for users
- `details` allows provider-specific debugging info without breaking the contract

**Alternatives considered:**
- Simple bool return: Loses error context needed for debugging
- Exception-based: Forces error handling at call site and complicates async flows
- Custom enum (ConnectionStatus.OK, ConnectionStatus.FAILED): Less intuitive than HTTP codes

### 4. API Endpoint Design

**Decision:** Add `POST /admin/test-connection/{provider}` to `routes_admin.py`.

**Rationale:**
- POST semantic for action-based operation (though it's idempotent, it's not a pure GET resource fetch)
- Path parameter `{provider}` keeps URL clean and RESTful
- Returns the same dict format as `test_connection()` for consistency
- Admin-only endpoint (protected by existing auth middleware)

**Alternatives considered:**
- GET request: Test is an action, not a resource fetch
- Query parameter `?provider=ibkr`: Less RESTful than path parameter
- Separate endpoint per provider (`/admin/test-ibkr`): Doesn't scale and breaks RESTful design

### 5. Error Handling Strategy

**Decision:** Catch provider-specific exceptions and map to standardized status codes:
- Authentication errors (invalid key, expired token) → 401
- Network/timeout errors → 503
- Provider service down/unavailable → 503
- Invalid configuration (missing credentials) → 400
- Success → 200

**Rationale:**
- HTTP status codes align with existing FastAPI error handling
- UI can display appropriate messages based on status code
- Logging captures full exception details for debugging while user sees friendly message

### 6. UI Integration

**Decision:** Add a "Test Connection" button next to each provider's API key input field in the admin panel. Display result (status code + message) inline with color-coding (green for success, red for failure, yellow for warnings).

**Rationale:**
- Immediate visual feedback without leaving the configuration page
- Status code displayed alongside message helps technical users debug
- Color-coded result is accessible and clear

## Risks / Trade-offs

**[Risk]** LSEG test opens a full session, which may be slow (2-5 seconds) and consume a session slot.  
**→ Mitigation:** Document expected delay and ensure session is closed immediately. Consider caching session for 60s if multiple tests are triggered.

**[Risk]** IBKR test may disconnect active users if TWS/Gateway has connection limits.  
**→ Mitigation:** Use `ib.isConnected()` first to avoid redundant connections. Document that test requires TWS/Gateway to be running.

**[Risk]** REST provider tests (Finnhub, Polygon, Schwab) may consume API quota if rate limits are tight.  
**→ Mitigation:** Use the most lightweight endpoint available (e.g., `/status` or `/quote` with a single symbol). Document quota consumption risk.

**[Risk]** Test failures may be transient (network blip, temporary service outage).  
**→ Mitigation:** Return specific error messages ("Network timeout — try again" vs "Invalid API key"). Avoid automatic retries to keep tests fast.

**[Risk]** OAuth token refresh for Schwab may complicate test logic.  
**→ Mitigation:** Test uses existing token without triggering refresh. If 401, message instructs user to refresh token manually.

## Migration Plan

1. Add `test_connection()` abstract method to base classes (`base.py`)
2. Implement `test_connection()` in each provider (`ibkr.py`, `lseg.py`, etc.)
3. Add API endpoint to `routes_admin.py` with basic tests
4. Add UI button and result display to admin panel
5. Deploy and test in staging with all providers
6. Document test behavior and expected response times per provider

**Rollback:** If test implementation causes issues (e.g., unexpected quota consumption or connection disruption), disable endpoint via feature flag or remove route handler. No data model changes are involved.

## Open Questions

- Should tests be cached (e.g., "last tested 2 minutes ago — success") to avoid redundant calls?
  - **Lean toward no:** Tests are on-demand and fast enough. Caching adds complexity.
  
- Should the endpoint support bulk testing (test all providers at once)?
  - **Lean toward no:** Keep it simple with single-provider testing. UI can trigger multiple tests sequentially if needed.

- Should failed tests trigger alerts or logging for monitoring?
  - **Yes:** Log failures at WARNING level with provider name and error details for ops visibility.
