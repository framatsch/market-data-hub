# Schwab OAuth Specification for MDH

## Purpose
Define expected behavior for the Schwab OAuth authorization, callback, and connection flow in Market Data Hub (MDH).

## Requirements

### Requirement: Start Schwab OAuth Authorization
The system SHALL let an authenticated admin begin a Schwab OAuth authorization by generating a PKCE code verifier and a CSRF `state`, persisting the verifier and the `state` server-side for short-lived lookup, and returning the Schwab authorization URL built from the provider's configured app credentials.

The endpoint SHALL require admin authorization, and SHALL use the global `schwab.api_key` and `schwab.app_secret` properties from `keys.db` as the OAuth `client_id`/`client_secret`, and the central `SCHWAB_REDIRECT_URI` setting (default `https://127.0.0.1`) as the `redirect_uri`. It SHALL fail with a configuration error when the `schwab.api_key` or `schwab.app_secret` is not set in the encrypted store.

#### Scenario: Admin requests an authorization URL
- **WHEN** an authenticated admin requests to connect Schwab
- **THEN** the system SHALL generate a PKCE code verifier and a random `state`
- **THEN** the system SHALL persist the verifier and the `state` for later lookup
- **THEN** the system SHALL return an authorization URL containing `client_id`, the configured `redirect_uri`, `code_challenge`, `code_challenge_method=S256`, and the generated `state`

#### Scenario: Schwab application credentials are not configured
- **WHEN** an admin requests an authorization URL but `schwab.api_key` or `schwab.app_secret` are missing from `keys.db`
- **THEN** the system SHALL respond with HTTP 400 indicating the Schwab app credentials must be set in the Admin UI first

### Requirement: OAuth Mode and Redirect URI Consistency
The system SHALL support two OAuth completion modes selected by a setting (or determined dynamically based on the environment): `paste` (the user pastes the redirect URL) and `callback` (Schwab redirects the browser to a server endpoint). At authorization time the system SHALL validate that the mode and the configured redirect URI are consistent.

### Requirement: Complete Schwab Connection by Automatic Callback
When configured for `callback`, the system SHALL expose an unauthenticated `GET` callback endpoint that Schwab redirects to with `code` and `state`. The endpoint SHALL validate the `state`, exchange the `code` for tokens using the provider's app credentials and the same `redirect_uri`, store the tokens as encrypted JSON, and redirect the browser back to the Admin UI with a success or error indication.

The callback SHALL never expose token values in the URL, response body, or logs.

#### Scenario: Valid callback completes the connection automatically
- **WHEN** Schwab redirects to the callback endpoint with a `code` and a `state` that matches a stored `state` correlation
- **THEN** the system SHALL exchange the `code` for tokens using the `schwab.api_key`/`schwab.app_secret` and the configured `redirect_uri`
- **THEN** the system SHALL persist the encrypted token properties into `keys.db` (e.g., as `schwab.token_json`) and clear the one-time verifier/state records
- **THEN** the system SHALL redirect the browser to the Admin UI indicating success

#### Scenario: Callback with an unknown or expired state
- **WHEN** the callback receives a `state` that does not match any stored correlation
- **THEN** the system SHALL NOT exchange the code and SHALL redirect indicating the authorization could not be matched (or expired)

### Requirement: Complete Schwab Connection by Pasted Redirect URL
When configured for `paste`, the system SHALL let an authenticated admin complete a Schwab connection by pasting the full redirect URL captured from the browser address bar. The system SHALL extract the `code` and `state` query parameters, validate the `state`, exchange the `code` for tokens via the PKCE `code_verifier`, and store the resulting tokens. This endpoint is authenticated and scoped to the admin.

Tokens SHALL be stored encrypted in `keys.db` (e.g., `schwab.token_json`). Raw tokens SHALL never be logged or returned in responses.

#### Scenario: Valid redirect URL completes the connection
- **WHEN** the admin pastes a redirect URL of the form `https://127.0.0.1/?code=<code>&state=<state>` whose `state` matches the persisted value
- **THEN** the system SHALL exchange the `code` for tokens using the stored `code_verifier`, `schwab.api_key`/`schwab.app_secret`, and `redirect_uri`
- **THEN** the system SHALL persist the token properties encrypted in `keys.db`
- **THEN** the system SHALL clear the one-time `code_verifier`/`state` record

### Requirement: Schwab Connection Status and Disconnect
The system SHALL report whether the Schwab provider has stored access/refresh tokens and SHALL allow an authenticated admin to disconnect by deleting the stored token properties. Status responses SHALL NOT include token values.

#### Scenario: Provider has stored tokens
- **WHEN** an authenticated admin queries the Schwab connection status
- **THEN** the system SHALL report the provider as connected (e.g., `{"provider": "schwab", "credential_name": "token_json", "set": true}`) without revealing token values

#### Scenario: Admin disconnects Schwab
- **WHEN** an authenticated admin disconnects Schwab
- **THEN** the system SHALL delete the `schwab.token_json` from `keys.db`

### Requirement: Transparent Access-Token Refresh
The system SHALL refresh an expired or soon-to-expire Schwab access token using the stored refresh token before making broker API calls, and SHALL persist the rotated access token and expiry. Schwab access tokens are valid for 30 minutes; refresh tokens have a hard 7-day lifetime from creation and cannot be extended.

#### Scenario: Access token expired at sync time
- **WHEN** a broker operation needs the Schwab access token and the stored expiry is in the past or within the refresh threshold
- **THEN** the system SHALL call the Schwab token endpoint with the stored refresh token
- **THEN** the system SHALL persist the new access token and expiry (and refresh token if rotated) into `keys.db` before proceeding

#### Scenario: Refresh token is invalid or expired
- **WHEN** the refresh call fails because the refresh token is no longer valid (e.g. the 7-day limit has elapsed, yielding `invalid_client`)
- **THEN** the system SHALL surface an actionable "reconnect required" error rather than a generic failure

### Requirement: Schwab Test Connection
The system SHALL provide a Schwab test-connection that verifies live API connectivity by fetching account numbers with a valid access token. A test SHALL only perform a network call when the provider is already connected via OAuth.

#### Scenario: Test connection on a connected provider
- **WHEN** a test connection is requested for Schwab which has stored tokens
- **THEN** the system SHALL obtain a valid access token (refreshing if needed) and call the Schwab accounts endpoint
- **THEN** the system SHALL report success when the call returns account data

#### Scenario: Test connection before the provider is connected
- **WHEN** a test connection is requested for Schwab which has no stored tokens
- **THEN** the system SHALL return an HTTP 400 indicating the provider must be connected via the Schwab OAuth flow first, without making a network call
