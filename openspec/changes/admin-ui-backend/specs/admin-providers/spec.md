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
`POST /api/admin/providers/{name}/enable` SHALL set `provider_config.enabled = true` in SQLite, and instantiate the provider in the registry without restarting the application.

#### Scenario: Successfully enable a disabled provider
- **WHEN** `POST /api/admin/providers/finnhub/enable` is called and finnhub is currently disabled
- **THEN** FinnhubProvider is instantiated, added to the registry, `provider_config.enabled` is set to `true`, and response is `{"name": "finnhub", "enabled": true, "status": "healthy"}`

#### Scenario: Enable already-enabled provider is idempotent
- **WHEN** `POST /api/admin/providers/schwab/enable` is called and schwab is already enabled
- **THEN** response is 200 with current status, no changes made

#### Scenario: Unknown provider name rejected
- **WHEN** `POST /api/admin/providers/nonexistent/enable` is called
- **THEN** response is HTTP 404 with `{"detail": "Unknown provider: nonexistent"}`

### Requirement: Disable a provider at runtime
`POST /api/admin/providers/{name}/disable` SHALL set `provider_config.enabled = false` in SQLite, call `close()` on the provider instance, and remove it from the registry.

#### Scenario: Successfully disable an enabled provider
- **WHEN** `POST /api/admin/providers/ibkr/disable` is called
- **THEN** `ibkr.close()` is called, IBKR is removed from registry, `provider_config.enabled` is set to `false`, response is `{"name": "ibkr", "enabled": false, "status": "disabled"}`

#### Scenario: In-flight requests complete gracefully
- **WHEN** a provider is disabled while a request is being processed by it
- **THEN** the in-flight request completes normally; only subsequent requests get 503 for that provider

### Requirement: IBKR gateway URL configurable
`PUT /api/admin/providers/ibkr/gateway` SHALL accept `{"host": "...", "port": 4001}` and persist the values in SQLite `provider_config.connection_config_json` for provider `ibkr`. The IBKR provider instance SHALL be restarted to pick up the new connection parameters.

#### Scenario: Update IBKR gateway URL
- **WHEN** `PUT /api/admin/providers/ibkr/gateway` is called with `{"host": "192.168.1.10", "port": 4001}`
- **THEN** IBKR provider is closed, config updated, provider re-instantiated, response confirms new settings

### Requirement: Provider runtime configuration endpoint
`GET /api/admin/providers/{name}/config` SHALL return runtime configuration for a provider. `PUT /api/admin/providers/{name}/config` SHALL update runtime configuration in SQLite and hot-reload the provider if any effective runtime value changed.

Runtime configuration SHALL include at minimum: `enabled`, `timeout_seconds`, `retry_count`, `retry_backoff_seconds`, `rate_limit_per_sec`, `circuit_breaker_enabled`, `circuit_breaker_failure_threshold`, `circuit_breaker_reset_seconds`, and provider-specific `connection_config`.

#### Scenario: Get provider runtime config
- **WHEN** `GET /api/admin/providers/schwab/config` is called
- **THEN** response includes `{"provider_name": "schwab", "enabled": true, "timeout_seconds": 30, "retry_count": 2, "rate_limit_per_sec": 5, "circuit_breaker_enabled": true, ...}`

#### Scenario: Update timeout and retry policy
- **WHEN** `PUT /api/admin/providers/finnhub/config` is called with `{"timeout_seconds": 10, "retry_count": 3, "retry_backoff_seconds": 0.5}`
- **THEN** the values are stored in SQLite and FinnhubProvider uses the new timeout/retry policy after hot-reload

#### Scenario: Update rate limit and circuit breaker
- **WHEN** `PUT /api/admin/providers/polygon/config` is called with `{"rate_limit_per_sec": 4, "circuit_breaker_enabled": true, "circuit_breaker_failure_threshold": 5, "circuit_breaker_reset_seconds": 60}`
- **THEN** the values are stored in SQLite and PolygonProvider uses the new rate-limit and circuit-breaker settings after hot-reload

#### Scenario: Invalid config rejected
- **WHEN** `PUT /api/admin/providers/schwab/config` is called with `{"timeout_seconds": -1}`
- **THEN** response is HTTP 422 and existing config remains unchanged

### Requirement: ProviderConfigRepository stores non-secret runtime config in SQLite
The system SHALL store non-secret provider runtime config in SQLite table `provider_config`. It SHALL not use `.env`, K8s Secrets, or process environment variables for admin-managed runtime config after initial defaults are loaded.

#### Scenario: Runtime config written to SQLite in K3s
- **WHEN** provider timeout is changed in a K3s deployment
- **THEN** `keys.db` is updated and no K8s Secret or ConfigMap is patched

#### Scenario: Runtime config written to SQLite locally
- **WHEN** provider rate limit is changed locally
- **THEN** `keys.db` is updated and `.env` is not modified
