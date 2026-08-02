## ADDED Requirements

### Requirement: Provider base classes SHALL include test_connection method
Each provider base class (`BasePriceProvider`, `BaseCompanyProvider`, `BaseOptionsProvider`, `BaseNewsProvider`) SHALL define an abstract `test_connection()` method that returns a standardized connection test result.

#### Scenario: Abstract method enforces implementation
- **WHEN** a new provider is created by inheriting from a base class
- **THEN** the provider MUST implement `test_connection()` or raise NotImplementedError

#### Scenario: test_connection returns standardized response
- **WHEN** `test_connection()` is called on any provider
- **THEN** it SHALL return a dict with keys: `status_code` (int), `success` (bool), `message` (str), `details` (dict)

### Requirement: IBKR provider SHALL test TWS/Gateway connectivity
The IBKR provider SHALL implement `test_connection()` to validate connectivity to Interactive Brokers TWS or Gateway.

#### Scenario: Successful connection to running TWS/Gateway
- **WHEN** TWS or Gateway is running and accessible
- **THEN** `test_connection()` SHALL return status_code 200, success True, message "Connected to IBKR", and details containing connection info

#### Scenario: TWS/Gateway not running
- **WHEN** TWS or Gateway is not running or unreachable
- **THEN** `test_connection()` SHALL return status_code 503, success False, message "IBKR TWS/Gateway not reachable", and details containing error info

#### Scenario: Invalid credentials
- **WHEN** credentials are invalid or rejected by IBKR
- **THEN** `test_connection()` SHALL return status_code 401, success False, message "Authentication failed", and details containing error info

### Requirement: LSEG provider SHALL test session and credentials
The LSEG provider SHALL implement `test_connection()` to validate Refinitiv session and credentials.

#### Scenario: Successful session open and lightweight request
- **WHEN** LSEG credentials are valid and session opens successfully
- **THEN** `test_connection()` SHALL return status_code 200, success True, message "LSEG session active", and close the session immediately after

#### Scenario: Invalid LSEG credentials
- **WHEN** APP_KEY, USERNAME, or PASSWORD is invalid
- **THEN** `test_connection()` SHALL return status_code 401, success False, message "LSEG authentication failed", and details containing error reason

#### Scenario: LSEG service unavailable
- **WHEN** LSEG service is down or unreachable
- **THEN** `test_connection()` SHALL return status_code 503, success False, message "LSEG service unavailable"

### Requirement: Finnhub provider SHALL test API key validity
The Finnhub provider SHALL implement `test_connection()` to validate the API key using a lightweight request.

#### Scenario: Valid Finnhub API key
- **WHEN** Finnhub API key is valid
- **THEN** `test_connection()` SHALL return status_code 200, success True, message "Finnhub API key valid"

#### Scenario: Invalid Finnhub API key
- **WHEN** Finnhub API key is invalid or missing
- **THEN** `test_connection()` SHALL return status_code 401, success False, message "Invalid Finnhub API key"

#### Scenario: Finnhub service error
- **WHEN** Finnhub API returns 5xx error or network timeout
- **THEN** `test_connection()` SHALL return status_code 503, success False, message "Finnhub service unavailable"

### Requirement: Schwab provider SHALL test OAuth token validity
The Schwab provider SHALL implement `test_connection()` to validate the OAuth token using a lightweight request.

#### Scenario: Valid Schwab OAuth token
- **WHEN** OAuth token is valid and not expired
- **THEN** `test_connection()` SHALL return status_code 200, success True, message "Schwab OAuth token valid"

#### Scenario: Expired or invalid Schwab token
- **WHEN** OAuth token is expired or invalid
- **THEN** `test_connection()` SHALL return status_code 401, success False, message "Schwab OAuth token expired or invalid"

#### Scenario: Schwab service error
- **WHEN** Schwab API returns error or network timeout
- **THEN** `test_connection()` SHALL return status_code 503, success False, message "Schwab service unavailable"

### Requirement: Polygon provider SHALL test API key validity
The Polygon provider SHALL implement `test_connection()` to validate the API key using a lightweight request.

#### Scenario: Valid Polygon API key
- **WHEN** Polygon API key is valid
- **THEN** `test_connection()` SHALL return status_code 200, success True, message "Polygon API key valid"

#### Scenario: Invalid Polygon API key
- **WHEN** Polygon API key is invalid or missing
- **THEN** `test_connection()` SHALL return status_code 401, success False, message "Invalid Polygon API key"

#### Scenario: Polygon service error
- **WHEN** Polygon API returns error or network timeout
- **THEN** `test_connection()` SHALL return status_code 503, success False, message "Polygon service unavailable"

### Requirement: Prixe provider SHALL test API key validity
The Prixe provider SHALL implement `test_connection()` to validate the API key using a lightweight request.

#### Scenario: Valid Prixe API key
- **WHEN** Prixe API key is valid
- **THEN** `test_connection()` SHALL return status_code 200, success True, message "Prixe API key valid"

#### Scenario: Invalid Prixe API key
- **WHEN** Prixe API key is invalid or missing
- **THEN** `test_connection()` SHALL return status_code 401, success False, message "Invalid Prixe API key"

#### Scenario: Prixe service error
- **WHEN** Prixe API returns error or network timeout
- **THEN** `test_connection()` SHALL return status_code 503, success False, message "Prixe service unavailable"

### Requirement: Admin API SHALL expose test-connection endpoint
The admin API SHALL provide a `POST /admin/test-connection/{provider}` endpoint that calls the provider's `test_connection()` method.

#### Scenario: Test connection for specific provider
- **WHEN** user sends POST request to `/admin/test-connection/ibkr`
- **THEN** endpoint SHALL call IBKR provider's `test_connection()` and return the result as JSON

#### Scenario: Invalid provider name
- **WHEN** user requests `/admin/test-connection/invalid_provider`
- **THEN** endpoint SHALL return 404 with message "Provider not found"

#### Scenario: Provider not enabled
- **WHEN** user requests test for a provider not in ENABLED_PROVIDERS config
- **THEN** endpoint SHALL return 404 with message "Provider not enabled"

#### Scenario: Authentication required
- **WHEN** unauthenticated user attempts to access endpoint
- **THEN** endpoint SHALL return 401 or redirect to login

### Requirement: UI SHALL provide test connection buttons
The admin UI SHALL display a "Test Connection" button for each provider with API key configuration.

#### Scenario: User clicks test connection button
- **WHEN** user clicks "Test Connection" button for a provider
- **THEN** UI SHALL send POST request to `/admin/test-connection/{provider}` and display result

#### Scenario: Display test success result
- **WHEN** test returns status_code 200 and success True
- **THEN** UI SHALL display green success message with status code and message text

#### Scenario: Display test failure result
- **WHEN** test returns success False with status_code 401, 400, or 503
- **THEN** UI SHALL display red error message with status code and message text

#### Scenario: Display provider-specific details
- **WHEN** test result includes details dict with additional info
- **THEN** UI SHALL display details in expandable section below the message

### Requirement: Test connection SHALL complete within timeout
All provider test_connection implementations SHALL complete within 10 seconds or return timeout error.

#### Scenario: Test completes quickly
- **WHEN** provider responds within 10 seconds
- **THEN** test SHALL return normal success or failure result

#### Scenario: Test times out
- **WHEN** provider does not respond within 10 seconds
- **THEN** test SHALL return status_code 503, success False, message "Connection test timeout"

### Requirement: Test connection failures SHALL be logged
All test connection failures SHALL be logged at WARNING level with provider name and error details.

#### Scenario: Failed test is logged
- **WHEN** `test_connection()` returns success False
- **THEN** system SHALL log warning with provider name, status_code, and error message

#### Scenario: Successful test is not logged at warning level
- **WHEN** `test_connection()` returns success True
- **THEN** system MAY log at INFO or DEBUG level but SHALL NOT log at WARNING level
