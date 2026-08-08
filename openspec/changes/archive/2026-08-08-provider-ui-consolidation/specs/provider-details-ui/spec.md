## ADDED Requirements

### Requirement: Unified Provider Details Panel
The system SHALL render a single `ProviderDetailsPanel` component for each provider in the Provider Management view. The panel SHALL contain two tabs: "Configuration" and "Connection / Auth". The same panel structure SHALL be used for all providers.

#### Scenario: Provider details panel renders tabs
- **WHEN** the user expands a provider accordion
- **THEN** the panel SHALL show a "Configuration" tab and a "Connection / Auth" tab

#### Scenario: Configuration tab content
- **WHEN** the user is on the Configuration tab for a non-IBKR provider
- **THEN** the panel SHALL display: Timeout (seconds), Retry Count, Retry Backoff (seconds), Rate Limit (per/sec), Circuit Breaker toggle, Circuit Breaker Failure Threshold, Circuit Breaker Reset Seconds, and Connection Config JSON textarea

#### Scenario: Configuration tab for IBKR — JSON textarea suppressed
- **WHEN** the user is on the Configuration tab for IBKR
- **THEN** the panel SHALL display all fields EXCEPT the Connection Config JSON textarea (which is suppressed to prevent conflicts with `IbkrConnectionSection`)

#### Scenario: Save configuration
- **WHEN** the user edits fields in the Configuration tab and clicks "Save"
- **THEN** the system SHALL call `PUT /api/admin/providers/{name}/config` and show a success or error snackbar

### Requirement: Connection / Auth Tab Content by Provider Type
The Connection / Auth tab SHALL render different components depending on the provider. Three variants exist: `ApiKeyAuthSection` (finnhub, polygon, lseg), `IbkrConnectionSection` (ibkr), and `ApiKeyAuthSection` + `SchwabOAuthSection` (schwab).

#### Scenario: API key providers (finnhub, polygon, lseg)
- **WHEN** the user opens the Connection / Auth tab for finnhub, polygon, or lseg
- **THEN** the section SHALL render `ApiKeyAuthSection` listing all credential keys with status indicators (configured = green chip, missing = grey chip)

#### Scenario: IBKR connection config
- **WHEN** the user opens the Connection / Auth tab for IBKR
- **THEN** the section SHALL render `IbkrConnectionSection` with all 6 gateway fields (host, port, client_id, account_id, env, market_data_type)

#### Scenario: Authentication tab for Schwab
- **WHEN** the user opens the Connection / Auth tab for the Schwab provider
- **THEN** the tab SHALL render BOTH `ApiKeyAuthSection` (for `api_key` and `app_secret` only) and `SchwabOAuthSection` (for OAuth token status and re-authorization) stacked vertically

#### Scenario: Edit API keys
- **WHEN** the user enters a value into a credential field and clicks "Save"
- **THEN** the system SHALL call `PUT /api/admin/credentials/{provider}` with only non-blank fields
- **THEN** show a success snackbar

#### Scenario: Blank value preserves existing key
- **WHEN** the user leaves a credential field blank and saves
- **THEN** the blank field SHALL be omitted from the request payload

### Requirement: Reduced Navigation
The sidebar navigation SHALL contain exactly three entries: Dashboard, Providers, Settings.

#### Scenario: Sidebar items
- **WHEN** the admin UI is loaded
- **THEN** the sidebar SHALL show Dashboard, Providers, and Settings — and NO other navigation items

#### Scenario: Removed pages no longer accessible
- **WHEN** the user navigates to `/admin/credentials`, `/admin/schwab-auth`, or `/admin/alerts`
- **THEN** the router SHALL redirect to `/admin` or show a 404 component

### Requirement: Auto-Expand via URL Parameter
`ProvidersPage` SHALL support a `?expand=<provider_name>` URL parameter. When present on mount, the named provider's accordion SHALL be automatically expanded and the "Connection / Auth" tab SHALL be active.

#### Scenario: ?expand=schwab auto-expands Schwab
- **WHEN** the user navigates to `/admin/providers?expand=schwab`
- **THEN** the Schwab accordion SHALL be expanded automatically
- **THEN** the "Connection / Auth" tab SHALL be active

#### Scenario: Dashboard Re-authorize button uses expand param
- **WHEN** the user clicks "Re-authorize" on the Dashboard Schwab expiry alert
- **THEN** the browser SHALL navigate to `/admin/providers?expand=schwab`
