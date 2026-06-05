## ADDED Requirements

### Requirement: Provider status overview
`GET /api/admin/providers` SHALL return the status of all known providers including their enabled state, health status, and any error message.

#### Scenario: All providers healthy
- **WHEN** all enabled providers are connected
- **THEN** response contains a list with `{"name": "schwab", "enabled": true, "status": "healthy", "error": null}` for each

#### Scenario: Provider paused due to auth expiry
- **WHEN** SchwabProvider has `_paused=True`
- **THEN** response includes `{"name": "schwab", "enabled": true, "status": "paused", "error": "Token expired — re-authorization required"}`

#### Scenario: Disabled provider shown
- **WHEN** a provider is not in `ENABLED_PROVIDERS`
- **THEN** response includes `{"name": "ibkr", "enabled": false, "status": "disabled", "error": null}`

### Requirement: Enable a provider at runtime
`POST /api/admin/providers/{name}/enable` SHALL add the provider to `ENABLED_PROVIDERS`, persist the change via the CredentialStore, and instantiate the provider in the registry without restarting the application.

#### Scenario: Successfully enable a disabled provider
- **WHEN** `POST /api/admin/providers/finnhub/enable` is called and finnhub is currently disabled
- **THEN** FinnhubProvider is instantiated, added to the registry, `ENABLED_PROVIDERS` is updated in storage, and response is `{"name": "finnhub", "enabled": true, "status": "healthy"}`

#### Scenario: Enable already-enabled provider is idempotent
- **WHEN** `POST /api/admin/providers/schwab/enable` is called and schwab is already enabled
- **THEN** response is 200 with current status, no changes made

#### Scenario: Unknown provider name rejected
- **WHEN** `POST /api/admin/providers/nonexistent/enable` is called
- **THEN** response is HTTP 404 with `{"detail": "Unknown provider: nonexistent"}`

### Requirement: Disable a provider at runtime
`POST /api/admin/providers/{name}/disable` SHALL remove the provider from `ENABLED_PROVIDERS`, persist the change, call `close()` on the provider instance, and remove it from the registry.

#### Scenario: Successfully disable an enabled provider
- **WHEN** `POST /api/admin/providers/ibkr/disable` is called
- **THEN** `ibkr.close()` is called, IBKR is removed from registry, `ENABLED_PROVIDERS` updated, response is `{"name": "ibkr", "enabled": false, "status": "disabled"}`

#### Scenario: In-flight requests complete gracefully
- **WHEN** a provider is disabled while a request is being processed by it
- **THEN** the in-flight request completes normally; only subsequent requests get 503 for that provider

### Requirement: IBKR gateway URL configurable
`PUT /api/admin/providers/ibkr/gateway` SHALL accept `{"host": "...", "port": 4001}` and persist `IBKR_HOST` and `IBKR_PORT` via CredentialStore. The IBKR provider instance SHALL be restarted to pick up the new connection parameters.

#### Scenario: Update IBKR gateway URL
- **WHEN** `PUT /api/admin/providers/ibkr/gateway` is called with `{"host": "192.168.1.10", "port": 4001}`
- **THEN** IBKR provider is closed, config updated, provider re-instantiated, response confirms new settings
