## ADDED Requirements

### Requirement: Generate Schwab OAuth2 authorization URL
`GET /api/admin/schwab/auth/url` SHALL return the Schwab OAuth2 authorization URL that the user must open in their browser to initiate re-authorization.

#### Scenario: Auth URL generated
- **WHEN** `GET /api/admin/schwab/auth/url` is called and Schwab credentials are configured
- **THEN** response is `{"auth_url": "https://api.schwabapi.com/v1/oauth/authorize?client_id=...&redirect_uri=..."}` with status 200

#### Scenario: Missing credentials returns error
- **WHEN** `SCHWAB_API_KEY` is not set and auth URL is requested
- **THEN** response is HTTP 503 with `{"detail": "Schwab credentials not configured"}`

### Requirement: Complete re-authorization via callback URL
`POST /api/admin/schwab/auth/callback` SHALL accept `{"received_url": "<full redirect URL from browser>"}`, call `schwab-py`'s `client_from_received_url()` in a thread (non-blocking), write the resulting token to the configured `SCHWAB_TOKEN_PATH`, and set `SchwabProvider._paused = False`.

#### Scenario: Successful re-authorization
- **WHEN** `POST /api/admin/schwab/auth/callback` is called with a valid received URL
- **THEN** token is written to `SCHWAB_TOKEN_PATH`, provider is unpaused, response is `{"status": "ok", "token_expires_at": "<ISO datetime>"}`

#### Scenario: Invalid callback URL rejected
- **WHEN** the received URL does not contain a valid OAuth2 code parameter
- **THEN** response is HTTP 400 with `{"detail": "Invalid callback URL: <reason from schwab-py>"}`

#### Scenario: Non-blocking execution
- **WHEN** `client_from_received_url()` is called
- **THEN** it is executed via `asyncio.to_thread()` and does not block the event loop

### Requirement: Schwab auth status endpoint
`GET /api/admin/schwab/auth/status` SHALL return the current state of the Schwab token including approximate age, expiry estimate, and paused state.

#### Scenario: Token present and valid
- **WHEN** `schwab_token.json` exists and token is not expired
- **THEN** response is `{"status": "active", "paused": false, "token_file_exists": true, "expires_at": "<ISO datetime>", "days_remaining": 5}`

#### Scenario: Provider paused
- **WHEN** `SchwabProvider._paused = True`
- **THEN** response is `{"status": "expired", "paused": true, "token_file_exists": true, "expires_at": null, "days_remaining": 0}`

#### Scenario: No token file
- **WHEN** `SCHWAB_TOKEN_PATH` does not exist
- **THEN** response is `{"status": "not_configured", "paused": false, "token_file_exists": false}`
