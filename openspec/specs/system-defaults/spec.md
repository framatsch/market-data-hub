# system-defaults Specification

## Purpose
Define database-backed system defaults (such as the default provider per data category) that admins manage at runtime via the Admin API and UI, replacing the former environment-variable defaults.
## Requirements
### Requirement: System Settings Repository
The backend SHALL maintain a `system_settings` key-value table in the SQLite database to store runtime defaults such as `default_price_provider`.

#### Scenario: Storing defaults
- **WHEN** a new default is saved
- **THEN** the value is persisted in the database and survives application restarts.

### Requirement: Dynamic Defaults Reload
The `ProviderRegistry` SHALL query the `system_settings` table during `reload_from_config()` to update the effective default providers, falling back to hardcoded defaults (e.g., 'ibkr' for prices) if the database is empty.

This hardcoded fallback SHALL NOT apply to `default_volatility_provider`, whose effective value SHALL be `None` when unset or when its configured provider is not loaded or does not implement `BaseVolatilityProvider`.

#### Scenario: Resolving defaults
- **WHEN** the system starts or reloads configuration
- **THEN** the `ProviderRegistry` uses the value from the database, completely ignoring any legacy environment variables.

### Requirement: Default Volatility Provider Setting
The `system_settings` allowlist SHALL include `default_volatility_provider`. The `ProviderRegistry` SHALL resolve it during reload against loaded providers implementing `BaseVolatilityProvider`, defaulting to `None` when unset or when the configured provider is not loaded or lacks the capability. `GET /api/admin/settings/defaults` SHALL return `default_volatility_provider` and `PUT /api/admin/settings/defaults` SHALL accept it.

#### Scenario: Admin sets LSEG as default volatility provider
- **WHEN** an admin sends `PUT /api/admin/settings/defaults` with `{"default_volatility_provider": "lseg"}` and LSEG is enabled
- **THEN** the value SHALL be persisted, the registry SHALL reload, and `GET /api/admin/settings/defaults` SHALL return `"default_volatility_provider": "lseg"`

#### Scenario: Configured provider lacks capability
- **WHEN** `default_volatility_provider` is set to a provider that does not implement `BaseVolatilityProvider`
- **THEN** the registry SHALL log a warning and treat the effective default as `None`

#### Scenario: Fresh installation
- **WHEN** the system starts without a stored `default_volatility_provider`
- **THEN** the effective default volatility provider SHALL be `None`

### Requirement: Admin Settings API
The backend SHALL provide `GET /api/admin/settings/defaults` and `PUT /api/admin/settings/defaults` to read and update default providers. These endpoints, like all other `/api/admin/*` endpoints, MUST be secured using `PrincipalDep` to enforce OIDC Bearer authentication if enabled.

#### Scenario: Fetching system defaults
- **WHEN** an admin queries `GET /api/admin/settings/defaults` with a valid Bearer token
- **THEN** the backend returns the current active defaults.

#### Scenario: Unauthorized access
- **WHEN** a client queries `GET /api/admin/settings/defaults` without a valid token (and OIDC is enabled)
- **THEN** the backend returns an HTTP 401 Unauthorized error.

### Requirement: Provider Capabilities API
The backend SHALL provide an endpoint `GET /api/admin/settings/capabilities` that returns a map of categories (prices, options, companies, news, volatility, earnings_upcoming, earnings_history, earnings) to a list of enabled provider names that implement that capability. `earnings_upcoming` and `earnings_history` SHALL list the providers implementing the respective earnings interface; `earnings` SHALL be their union.

#### Scenario: Determining eligible defaults
- **WHEN** the Admin UI needs to populate dropdowns
- **THEN** the capabilities API returns which providers are eligible for each domain.

#### Scenario: Volatility category present
- **WHEN** LSEG is enabled and `GET /api/admin/settings/capabilities` is called
- **THEN** the response SHALL contain a `volatility` key whose list includes `lseg`

#### Scenario: Earnings categories present
- **WHEN** EarningsAPI and Financial Datasets are enabled and `GET /api/admin/settings/capabilities` is called
- **THEN** `earnings_upcoming` SHALL list only `earningsapi`, `earnings_history` SHALL list both, and `earnings` SHALL list both

### Requirement: System Defaults UI
The Admin UI SHALL include a System Defaults panel that allows selecting the default provider for each category (prices, options, companies, news, volatility, upcoming earnings, earnings history) from a dropdown of eligible providers.

#### Scenario: Admin updates defaults
- **WHEN** an admin changes the default price provider from IBKR to LSEG and saves
- **THEN** the frontend calls `PUT /api/admin/settings/defaults`, which triggers a backend config reload, making LSEG the new active default for price endpoints.

#### Scenario: Admin selects default volatility provider
- **WHEN** an admin opens the System Defaults panel
- **THEN** a "Default Volatility Provider" dropdown SHALL list the providers from the `volatility` capability category and saving SHALL send `default_volatility_provider`

#### Scenario: Admin selects earnings defaults
- **WHEN** an admin opens the System Defaults panel
- **THEN** a "Default Upcoming Earnings Provider" dropdown SHALL list the `earnings_upcoming` providers and a "Default Earnings History Provider" dropdown the `earnings_history` providers, and saving SHALL send `default_earnings_upcoming_provider` and `default_earnings_history_provider`

### Requirement: Default Earnings Provider Setting
The `system_settings` allowlist SHALL include `default_earnings_upcoming_provider` and `default_earnings_history_provider`. The `ProviderRegistry` SHALL resolve each during reload against loaded providers implementing `BaseEarningsUpcomingProvider` or `BaseEarningsHistoryProvider` respectively, defaulting to `None` when unset or when the configured provider is not loaded or lacks the interface. The former setting `default_earnings_provider` SHALL be migrated once: when it is stored and a new setting is unset, its value SHALL be copied into each new setting whose interface the provider implements, and it SHALL then be removed. `PUT /api/admin/settings/defaults` SHALL still accept `default_earnings_provider` as a shorthand that sets both new settings where the provider implements the interface. `GET /api/admin/settings/defaults` SHALL return both new settings.

#### Scenario: Admin sets the earnings defaults
- **WHEN** an admin sends `PUT /api/admin/settings/defaults` with `{"default_earnings_upcoming_provider": "earningsapi", "default_earnings_history_provider": "financialdatasets"}` and both are enabled
- **THEN** the values SHALL be persisted, the registry SHALL reload, and `GET /api/admin/settings/defaults` SHALL return both

#### Scenario: Configured provider lacks the interface
- **WHEN** `default_earnings_upcoming_provider` is set to `financialdatasets`
- **THEN** the registry SHALL log a warning and treat the effective upcoming default as `None`

#### Scenario: Migration of the former setting
- **WHEN** the system starts with a stored `default_earnings_provider: "financialdatasets"` and no new settings
- **THEN** `default_earnings_history_provider` SHALL be `financialdatasets`, `default_earnings_upcoming_provider` SHALL stay unset, and the former setting SHALL be removed

#### Scenario: Shorthand
- **WHEN** an admin sends `PUT /api/admin/settings/defaults` with `{"default_earnings_provider": "earningsapi"}`
- **THEN** both new settings SHALL be `earningsapi`

#### Scenario: Fresh installation
- **WHEN** the system starts without stored earnings defaults
- **THEN** both effective earnings defaults SHALL be `None`

