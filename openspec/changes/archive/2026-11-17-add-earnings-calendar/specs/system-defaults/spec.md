## ADDED Requirements

### Requirement: Default Earnings Provider Setting
The `system_settings` allowlist SHALL include `default_earnings_provider`. The `ProviderRegistry` SHALL resolve it during reload against loaded providers implementing `BaseEarningsProvider`, defaulting to `None` when unset or when the configured provider is not loaded or lacks the capability. `GET /api/admin/settings/defaults` SHALL return `default_earnings_provider` and `PUT /api/admin/settings/defaults` SHALL accept it.

#### Scenario: Admin sets Alpha Vantage as default earnings provider
- **WHEN** an admin sends `PUT /api/admin/settings/defaults` with `{"default_earnings_provider": "alphavantage"}` and Alpha Vantage is enabled
- **THEN** the value SHALL be persisted, the registry SHALL reload, and `GET /api/admin/settings/defaults` SHALL return `"default_earnings_provider": "alphavantage"`

#### Scenario: Configured provider lacks capability
- **WHEN** `default_earnings_provider` is set to a provider that does not implement `BaseEarningsProvider`
- **THEN** the registry SHALL log a warning and treat the effective default as `None`

#### Scenario: Fresh installation
- **WHEN** the system starts without a stored `default_earnings_provider`
- **THEN** the effective default earnings provider SHALL be `None`

## MODIFIED Requirements

### Requirement: Provider Capabilities API
The backend SHALL provide an endpoint `GET /api/admin/settings/capabilities` that returns a map of categories (prices, options, companies, news, volatility, earnings) to a list of enabled provider names that implement that capability.

#### Scenario: Determining eligible defaults
- **WHEN** the Admin UI needs to populate dropdowns
- **THEN** the capabilities API returns which providers are eligible for each domain.

#### Scenario: Volatility category present
- **WHEN** LSEG is enabled and `GET /api/admin/settings/capabilities` is called
- **THEN** the response SHALL contain a `volatility` key whose list includes `lseg`

#### Scenario: Earnings category present
- **WHEN** Alpha Vantage is enabled and `GET /api/admin/settings/capabilities` is called
- **THEN** the response SHALL contain an `earnings` key whose list includes `alphavantage`

### Requirement: System Defaults UI
The Admin UI SHALL include a System Defaults panel that allows selecting the default provider for each category (prices, options, companies, news, volatility, earnings) from a dropdown of eligible providers.

#### Scenario: Admin updates defaults
- **WHEN** an admin changes the default price provider from IBKR to LSEG and saves
- **THEN** the frontend calls `PUT /api/admin/settings/defaults`, which triggers a backend config reload, making LSEG the new active default for price endpoints.

#### Scenario: Admin selects default volatility provider
- **WHEN** an admin opens the System Defaults panel
- **THEN** a "Default Volatility Provider" dropdown SHALL list the providers from the `volatility` capability category and saving SHALL send `default_volatility_provider`

#### Scenario: Admin selects default earnings provider
- **WHEN** an admin opens the System Defaults panel
- **THEN** a "Default Earnings Provider" dropdown SHALL list the providers from the `earnings` capability category and saving SHALL send `default_earnings_provider`
