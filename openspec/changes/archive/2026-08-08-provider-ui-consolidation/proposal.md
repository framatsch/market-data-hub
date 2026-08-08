## Why

The admin UI has several separate navigation entries (Credentials, Schwab Auth, Alerts) that conceptually belong to provider configuration. This forces the user to switch between pages to fully set up a single provider. The Schwab page is also a dead-end with a manual copy-paste OAuth flow, even though an automatic backend callback would be possible.

## What Changes

- **Removed**: Sidebar entry "Credentials" (separate page) — API Keys are integrated into Provider Details
- **Removed**: Sidebar entry "Schwab Auth" (separate page) — OAuth flow is integrated into Schwab Provider Details
- **Removed**: Sidebar entry "Alerts" (separate page) — Webhook configuration is completely removed; Schwab token expiry is monitored via log file / Grafana
- **Removed**: `AlertsPage.tsx`, `SchwabAuthPage.tsx`, `CredentialsPage.tsx`
- **New**: Abstract `AuthSection` components (3 variants):
  - `ApiKeyAuthSection` — editable API key list (for finnhub, polygon, lseg, Schwab)
  - `IbkrConnectionSection` — Host/Port configuration for IBKR Gateway (no API keys!)
  - `SchwabOAuthSection` — OAuth status + "Re-authorize" button with automatic browser redirect flow
- **New**: `ProviderDetailsPanel` — base component shared by all providers (Config + Auth in one)
- **New**: Chip filter on `ProvidersPage` (All / Active / Inactive / Healthy / Not Configured)
- **New**: Automatic Schwab OAuth callback via backend redirect (`/api/admin/schwab/callback`) — no more manual copy-paste
- **Changed**: Navigation: only Dashboard, Providers, Settings
- **Changed**: `SettingsPage` — retains default provider settings, keeps Logo URL; **BREAKING** only for Alert users who had a webhook URL configured

## Capabilities

### New Capabilities

- `provider-details-ui`: Unified Provider Details component with Config + Auth sections, usable by all providers; Schwab variant extends the base
- `api-key-auth-ui`: Inline API Key management within Provider Details (list of all keys, editable, saveable)
- `ibkr-connection-ui`: IBKR-specific Host/Port configuration in the Authentication tab (no API keys, gateway connection parameters instead)
- `schwab-oauth-auto-flow`: Automatic OAuth2 redirect flow for Schwab token refresh — backend intercepts callback, no manual URL copy-paste
- `provider-filter-chips`: Status filter chips on the Provider overview (All / Active / Inactive / Healthy / Not Configured)

### Modified Capabilities

- `configurable-providers`: Navigation and edit interface fundamentally change; Credentials move into Provider Details

## Impact

- **Frontend**: `admin/src/` — Sidebar, Router, all pages except Dashboard and Settings restructured; 3 pages removed, new components under `components/provider/`
- **Backend**: New endpoint `GET /api/admin/schwab/callback?code=...&state=...` for automatic OAuth callback; existing Schwab auth endpoints remain as base
- **Backend**: `DELETE /api/admin/alerts/webhook` or endpoints can be removed (no UI anymore)
- **No DB migration**: Credential storage and Provider Config remain unchanged
