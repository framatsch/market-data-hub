## ADDED Requirements

### Requirement: System Settings Repository
The backend SHALL maintain a `system_settings` key-value table in the SQLite database to store runtime defaults such as `default_price_provider`.

#### Scenario: Storing defaults
- **WHEN** a new default is saved
- **THEN** the value is persisted in the database and survives application restarts.

### Requirement: Dynamic Defaults Reload
The `ProviderRegistry` SHALL query the `system_settings` table during `reload_from_config()` to update the effective default providers, falling back to hardcoded defaults (e.g., 'ibkr' for prices) if the database is empty.

#### Scenario: Resolving defaults
- **WHEN** the system starts or reloads configuration
- **THEN** the `ProviderRegistry` uses the value from the database, completely ignoring any legacy environment variables.

### Requirement: Admin Settings API
The backend SHALL provide `GET /api/admin/settings/defaults` and `PUT /api/admin/settings/defaults` to read and update default providers. These endpoints, like all other `/api/admin/*` endpoints, MUST be secured using `PrincipalDep` to enforce OIDC Bearer authentication if enabled.

#### Scenario: Fetching system defaults
- **WHEN** an admin queries `GET /api/admin/settings/defaults` with a valid Bearer token
- **THEN** the backend returns the current active defaults.

#### Scenario: Unauthorized access
- **WHEN** a client queries `GET /api/admin/settings/defaults` without a valid token (and OIDC is enabled)
- **THEN** the backend returns an HTTP 401 Unauthorized error.

### Requirement: Provider Capabilities API
The backend SHALL provide an endpoint `GET /api/admin/settings/capabilities` that returns a map of categories (prices, options, companies, news) to a list of enabled provider names that implement that capability.

#### Scenario: Determining eligible defaults
- **WHEN** the Admin UI needs to populate dropdowns
- **THEN** the capabilities API returns which providers are eligible for each domain.

### Requirement: System Defaults UI
The Admin UI SHALL include a System Defaults panel that allows selecting the default provider for each category from a dropdown of eligible providers.

#### Scenario: Admin updates defaults
- **WHEN** an admin changes the default price provider from IBKR to LSEG and saves
- **THEN** the frontend calls `PUT /api/admin/settings/defaults`, which triggers a backend config reload, making LSEG the new active default for price endpoints.

## REMOVED Requirements

### Requirement: Environment Variable Defaults
**Reason**: Replaced by dynamic, database-backed system settings manageable via the Admin UI.
**Migration**: Remove `DEFAULT_PRICE_PROVIDER`, `DEFAULT_COMPANY_PROVIDER`, `DEFAULT_OPTIONS_PROVIDER`, and `DEFAULT_NEWS_PROVIDER` from `app/config.py` (and `.env.example`/`README.md`), and remove all legacy fallback logic relying on them from `ProviderRegistry`.
