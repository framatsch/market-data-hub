## ADDED Requirements

### Requirement: Schwab Authorization URL Generation via get_auth_context
The backend SHALL use `schwab.auth.get_auth_context(api_key, callback_url=settings.SCHWAB_CALLBACK_URL)` to generate the Schwab authorization URL. The resulting `AuthContext` object contains a random `state` value and the `authorization_url`. The backend SHALL store the `(auth_context, timestamp)` tuple in a short-lived in-memory dict keyed by `state` (TTL: 10 minutes). The endpoint returns `{"auth_url": auth_context.authorization_url}`.

#### Scenario: Auth URL generated and state stored
- **WHEN** `GET /api/admin/schwab/auth/url` is called
- **THEN** the backend SHALL call `get_auth_context()` with `api_key` and `settings.SCHWAB_CALLBACK_URL`
- **THEN** store `(auth_context, now())` in the state store under the generated `state` key
- **THEN** evict any stored state entries older than 10 minutes
- **THEN** return `{"auth_url": auth_context.authorization_url}`

#### Scenario: Schwab credentials missing
- **WHEN** `api_key` or `app_secret` are not configured
- **THEN** return HTTP 503 "Schwab credentials not configured"

### Requirement: Automatic Schwab OAuth Callback Endpoint
The backend SHALL expose an **unauthenticated** `GET /api/admin/schwab/callback` endpoint (no `PrincipalDep` dependency). It accepts `code` and `state` as query parameters.

Security is provided by the `state` CSRF guard: the `state` must match a non-expired entry in the in-memory state store. Calls with unknown or expired `state` are rejected.

#### Scenario: Valid callback — successful token exchange
- **WHEN** `GET /api/admin/schwab/callback?code=<code>&state=<valid_state>` is called
- **THEN** the backend SHALL look up the stored `auth_context` by `state` and pop it from the store
- **THEN** call `client_from_received_url(api_key, app_secret, auth_context=stored_auth_context, received_url=str(request.url), token_write_func=...)` to exchange the code for tokens
- **THEN** persist the token via `key_repo.save("schwab", "token_json", token_json)`
- **THEN** call `registry.unpause_provider("schwab")`
- **THEN** clear any pending `callback_error` in the transient error store
- **THEN** return HTTP 200 with HTML body "Authorization successful. You may close this tab."

#### Scenario: Invalid or expired state
- **WHEN** the `state` param is not found in the store or has expired
- **THEN** write `{status: "callback_error", error: "Invalid or expired state. Please retry authorization."}` to the transient error store
- **THEN** return HTTP 400 with HTML error body

#### Scenario: Token exchange fails
- **WHEN** `client_from_received_url` raises an exception
- **THEN** write `{status: "callback_error", error: str(exception)}` to the transient error store (TTL: 5 minutes)
- **THEN** return HTTP 400 with HTML error body describing the failure

### Requirement: Transient Error State for Polling Detection
The backend SHALL maintain a transient in-memory error store for Schwab OAuth failures. `GET /api/admin/schwab/auth/status` SHALL check this store and return `{"status": "callback_error", "error": "..."}` when a recent error (within 5 minutes) exists.

#### Scenario: Status reflects callback error
- **WHEN** a callback error has been written to the transient store
- **AND** `GET /api/admin/schwab/auth/status` is called within 5 minutes of the error
- **THEN** the response SHALL be `{"status": "callback_error", "error": "<error message>", "paused": true}`

#### Scenario: Error store cleared on success
- **WHEN** a successful token exchange occurs
- **THEN** any pending `callback_error` SHALL be cleared from the transient store

### Requirement: Schwab OAuth Status Display and Polling in Frontend
The `SchwabOAuthSection` component SHALL fetch token status from `GET /api/admin/schwab/auth/status` using React Query key `['schwab', 'status']`. On click of "Re-authorize":
1. Call `GET /api/admin/schwab/auth/url`, open returned URL in new tab via `window.open(auth_url)`
2. Enter "Waiting for authorization..." state with spinner
3. Poll `GET /api/admin/schwab/auth/status` every 2 seconds, maximum 60 seconds

#### Scenario: Polling detects success
- **WHEN** polling returns `status: "active"`
- **THEN** show success snackbar "Schwab successfully re-authorized", stop polling, refresh status display

#### Scenario: Polling detects backend error
- **WHEN** polling returns `status: "callback_error"`
- **THEN** show error snackbar with the `error` field from the response, stop polling immediately
- **THEN** show "Try Again" button

#### Scenario: Polling timeout
- **WHEN** 60 seconds elapse without `status: "active"` or `status: "callback_error"`
- **THEN** stop polling and show message "Authorization timed out or was cancelled." with "Try Again" button

#### Scenario: Color-coded token status
- **WHEN** `status: "active"` and `days_remaining > 3`
- **THEN** show green "ACTIVE" label
- **WHEN** `status: "active"` and `days_remaining <= 3`
- **THEN** show orange warning chip with days remaining
- **WHEN** `status: "expired"` or `status: "not_configured"` or `status: "callback_error"`
- **THEN** show red label

### Requirement: SCHWAB_CALLBACK_URL Configuration
The `SCHWAB_CALLBACK_URL` setting SHALL be set to the backend's own callback URL (e.g. `http://localhost:8000/api/admin/schwab/callback`). The default value of `https://127.0.0.1:8182` is invalid for this flow. The Settings page SHALL display an informational note about the required `redirect_uri` registration in the Schwab Developer Portal.

#### Scenario: Settings page shows Schwab redirect_uri info
- **WHEN** the Settings page is loaded
- **THEN** an info note SHALL be visible: "Schwab OAuth requires registering `<SCHWAB_CALLBACK_URL>` as the redirect_uri in the Schwab Developer Portal."

### Requirement: Old POST Callback Endpoint Deprecated
The existing `POST /api/admin/schwab/auth/callback` endpoint SHALL be marked as deprecated (`deprecated=True` on the FastAPI route). It remains functional for one release cycle to support rollback. It is no longer called by any UI component after this change.

#### Scenario: Deprecated endpoint still accepts requests
- **WHEN** `POST /api/admin/schwab/auth/callback` is called with `{received_url: "..."}` and valid Schwab credentials
- **THEN** the endpoint SHALL still perform token exchange and return success
- **THEN** the OpenAPI schema SHALL mark it as deprecated
