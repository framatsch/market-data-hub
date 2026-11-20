## ADDED Requirements

### Requirement: IBKR Web API provider SHALL test the Client Portal Gateway session
The `ibkrweb` provider SHALL implement `test_connection()` by checking the gateway and the brokerage session (`POST /iserver/auth/status`, and the brokerage initialisation when the session is `brokerage_pending`). It SHALL NOT send `ssodh/init` with `compete: true` unless `compete` is configured, and SHALL use at most three upstream requests.

#### Scenario: Session ready
- **WHEN** the user is logged in at the gateway and the brokerage session is authenticated
- **THEN** `test_connection()` SHALL return status_code 200, success True, message "Connected to IBKR Web API", and details with `base_url`, `state: "ready"`, `authenticated`, `competing`, `server_version` and the number of accounts

#### Scenario: Gateway not running
- **WHEN** the gateway at `base_url` is not reachable
- **THEN** `test_connection()` SHALL return status_code 503, success False, message "Client Portal Gateway not reachable", and details containing `base_url` and the error

#### Scenario: Login required
- **WHEN** the gateway answers HTTP 401 or reports `connected: false`
- **THEN** `test_connection()` SHALL return status_code 401, success False, message "Login required at the Client Portal Gateway", and details containing `login_url`

#### Scenario: Competing session
- **WHEN** the gateway reports `competing: true` and `compete` is `false`
- **THEN** `test_connection()` SHALL return status_code 409, success False, message "Another IBKR session of this username holds the brokerage session", and details with `state: "competing"`

#### Scenario: Penalty pause
- **WHEN** the provider is in the 429 penalty pause
- **THEN** `test_connection()` SHALL return status_code 429, success False, without an upstream request, and details with `retry_after_seconds`
