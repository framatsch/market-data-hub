## Why

Provider API keys can fail silently or become invalid without warning. Users currently have no way to verify that their configured credentials are working correctly before attempting to fetch data. This creates a poor user experience when keys expire or are misconfigured, leading to cryptic errors during actual data requests instead of clear validation feedback.

## What Changes

- Add a `/test-connection/{provider}` endpoint that validates provider credentials without fetching real data
- Implement `test_connection()` method in the base provider interface
- Implement provider-specific connection tests for all providers (IBKR, LSEG, Finnhub, Schwab, Polygon, Prixe)
- Return HTTP status code + detailed response indicating success/failure with error details
- Add UI integration in the admin panel with a "Test Connection" button for each provider
- Display connection test results (status code + response message) in the UI

## Capabilities

### New Capabilities
- `provider-connection-test`: API endpoint and provider methods to validate credentials and connectivity for each data provider

### Modified Capabilities
<!-- No existing capabilities are being modified at the spec level -->

## Impact

**Affected Code:**
- `app/providers/base.py` - add `test_connection()` abstract method
- `app/providers/ibkr.py` - implement connection test (check TWS/Gateway connectivity)
- `app/providers/lseg.py` - implement connection test (validate session + credentials)
- `app/providers/finnhub.py` - implement connection test (validate API key with lightweight request)
- `app/providers/schwab.py` - implement connection test (validate OAuth token)
- `app/providers/polygon.py` - implement connection test (validate API key)
- `app/providers/prixe.py` - implement connection test (validate API key)
- `app/api/routes_admin.py` - add `/test-connection/{provider}` endpoint
- Admin UI templates/components - add test connection buttons and result display

**APIs:**
- New endpoint: `POST /admin/test-connection/{provider}` - returns `{status_code: int, success: bool, message: str, details: dict}`

**Dependencies:**
- No new dependencies required - uses existing provider client libraries
