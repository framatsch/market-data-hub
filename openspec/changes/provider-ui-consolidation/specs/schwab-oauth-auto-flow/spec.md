## ADDED Requirements

### Requirement: Schwab OAuth Status Display
The `SchwabOAuthSection` component SHALL display the current Schwab token status. Displayed fields: Token Status (ACTIVE/EXPIRED/MISSING as colored label), Days Remaining (if applicable), and Expires At datetime.

#### Scenario: Active token display
- **WHEN** the Schwab token is active and has more than 3 days remaining
- **THEN** the section SHALL show a green "ACTIVE" label and days remaining

#### Scenario: Expiring token warning
- **WHEN** fewer than 3 days remain
- **THEN** the section SHALL show an orange warning chip with days remaining

#### Scenario: Expired or missing token
- **WHEN** the token is expired or missing
- **THEN** the section SHALL show a red "EXPIRED" or "MISSING" label

### Requirement: Automatic Schwab Re-Authorization Flow
The `SchwabOAuthSection` SHALL provide a "Re-authorize" button. Clicking it SHALL initiate an automatic OAuth2 PKCE-free flow using the Backend callback endpoint — no manual URL copy-paste.

#### Scenario: Initiate re-authorization
- **WHEN** the user clicks "Re-authorize"
- **THEN** the system SHALL call `GET /api/admin/schwab/auth/url` to retrieve the authorization URL
- **THEN** the system SHALL open the URL in a new browser tab via `window.open(auth_url)`
- **THEN** the UI SHALL enter a "Waiting for authorization..." state with a spinner

#### Scenario: Automatic token exchange
- **WHEN** the user completes Schwab login and Schwab redirects to `http://localhost:8000/api/admin/schwab/callback?code=...&state=...`
- **THEN** the backend SHALL exchange the code for tokens and store them
- **THEN** the backend SHALL return an HTML page with message "Authorization successful. You may close this tab."

#### Scenario: Poll for completion
- **WHEN** the UI is in "Waiting for authorization..." state
- **THEN** the system SHALL poll `GET /api/admin/schwab/auth/status` every 2 seconds for up to 60 seconds
- **WHEN** polling returns `status: "active"`
- **THEN** the UI SHALL exit waiting state, show a success snackbar "Schwab successfully re-authorized", and display updated token status

#### Scenario: Polling timeout
- **WHEN** 60 seconds elapse without receiving `status: "active"`
- **THEN** the UI SHALL stop polling and show an error message "Authorization timed out. Please try again." with a "Try Again" button

#### Scenario: Backend callback error
- **WHEN** the backend receives an invalid code or the token exchange fails
- **THEN** the backend SHALL return an HTML error page with a clear error message
- **THEN** the UI polling SHALL receive an error status and exit waiting state with an error snackbar

### Requirement: Backend Schwab Callback Endpoint
The backend SHALL expose `GET /api/admin/schwab/callback` that accepts `code` and `state` query parameters, exchanges the authorization code for access and refresh tokens, persists the tokens, and returns an HTML response.

#### Scenario: Successful callback
- **WHEN** `GET /api/admin/schwab/callback?code=<valid_code>&state=<valid_state>` is called
- **THEN** the backend SHALL exchange the code using the stored code verifier
- **THEN** persist the access token and refresh token with expiry
- **THEN** return HTTP 200 with HTML body "Authorization successful. You may close this tab."

#### Scenario: Invalid or expired code
- **WHEN** the code is invalid or expired
- **THEN** the backend SHALL return HTTP 400 with HTML body explaining the error

#### Scenario: Status endpoint reflects new token
- **WHEN** token exchange succeeds
- **THEN** `GET /api/admin/schwab/auth/status` SHALL immediately return `{"status": "active", "days_remaining": N}`
