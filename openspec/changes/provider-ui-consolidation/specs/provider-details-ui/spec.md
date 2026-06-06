## ADDED Requirements

### Requirement: Unified Provider Details Panel
The system SHALL render a single `ProviderDetailsPanel` component for each provider in the Provider Management view. The panel SHALL contain two tabs: "Configuration" and "Authentication". The same panel structure SHALL be used for all providers; Schwab MAY extend it with additional OAuth-specific content in the Authentication tab.

#### Scenario: Provider details panel renders tabs
- **WHEN** the user expands a provider accordion
- **THEN** the panel SHALL show a "Configuration" tab and an "Authentication" tab

#### Scenario: Configuration tab content
- **WHEN** the user is on the Configuration tab
- **THEN** the panel SHALL display: Timeout (seconds), Retry Count, Retry Backoff (seconds), Rate Limit (per/sec), Circuit Breaker toggle, Circuit Breaker Failure Threshold, Circuit Breaker Reset Seconds, and Connection Config JSON textarea

#### Scenario: Save configuration
- **WHEN** the user edits fields in the Configuration tab and clicks "Save"
- **THEN** the system SHALL call `PUT /api/admin/providers/{name}/config` and show a success or error snackbar

### Requirement: Authentication Tab Content by Provider Type
The Authentication tab SHALL render different components depending on the provider. Three variants exist: `ApiKeyAuthSection` (finnhub, polygon, lseg), `IbkrConnectionSection` (ibkr), and `SchwabOAuthSection` + `ApiKeyAuthSection` (schwab).

#### Scenario: API key providers (finnhub, polygon, lseg)
- **WHEN** the user opens the Authentication tab for finnhub, polygon, or lseg
- **THEN** the section SHALL render `ApiKeyAuthSection` listing all credential keys with status indicators (configured = green chip, missing = grey chip)

#### Scenario: IBKR connection config
- **WHEN** the user opens the Authentication tab for IBKR
- **THEN** the section SHALL render `IbkrConnectionSection` with Host and Port fields (not API keys)

#### Scenario: Edit IBKR host/port
- **WHEN** the user edits host or port in the IBKR connection section and clicks "Save"
- **THEN** the system SHALL call `PUT /api/admin/providers/ibkr/gateway` with `{"host": "...", "port": ...}` and show a success snackbar

#### Scenario: IBKR host/port pre-filled from config
- **WHEN** the IBKR connection section loads
- **THEN** host SHALL be pre-filled from `connection_config.host` and port from `connection_config.port` (from `GET /api/admin/providers/ibkr/config`)

#### Scenario: Authentication tab for Schwab
- **WHEN** the user opens the Authentication tab for the Schwab provider
- **THEN** the tab SHALL render BOTH `ApiKeyAuthSection` (for `api_key`, `app_secret` credentials) and `SchwabOAuthSection` (for OAuth token status and re-authorization) stacked vertically

#### Scenario: Edit API keys
- **WHEN** the user enters a value into a credential field and clicks "Save"
- **THEN** the system SHALL call `PUT /api/admin/credentials/{provider}` and show a success snackbar

#### Scenario: Empty value preserves existing key
- **WHEN** the user leaves a credential field blank and saves
- **THEN** the existing stored value SHALL be preserved (not overwritten)

### Requirement: Reduced Navigation
The sidebar navigation SHALL contain exactly three entries: Dashboard, Providers, Settings.

#### Scenario: Sidebar items
- **WHEN** the admin UI is loaded
- **THEN** the sidebar SHALL show Dashboard, Providers, and Settings — and NO other navigation items

#### Scenario: Removed pages no longer accessible
- **WHEN** the user navigates to `/admin/credentials`, `/admin/schwab-auth`, or `/admin/alerts`
- **THEN** the router SHALL redirect to `/admin` or show a 404 component
