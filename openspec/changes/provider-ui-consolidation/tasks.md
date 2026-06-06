## 1. Backend — Schwab OAuth Callback Endpoint

- [ ] 1.1 Add `GET /api/admin/schwab/callback` endpoint in `app/api/routes_admin.py` (or equivalent Schwab admin routes file) accepting `code` and `state` query params
- [ ] 1.2 Implement token exchange logic in `app/providers/schwab.py`: use stored PKCE code verifier (or client credentials flow per Schwab API) to exchange `code` for `access_token` + `refresh_token`
- [ ] 1.3 Persist the new tokens and expiry to the existing Schwab credential store
- [ ] 1.4 Return HTML response on success: "Authorization successful. You may close this tab."
- [ ] 1.5 Return HTML error response on failure (invalid code, expired, etc.) with clear error message
- [ ] 1.6 Verify `GET /api/admin/schwab/auth/status` immediately reflects updated token after successful callback

## 2. Backend — Cleanup Alerts Endpoints (optional deprecation)

- [ ] 2.1 Mark `GET /api/admin/alerts/webhook`, `PUT /api/admin/alerts/webhook`, `POST /api/admin/alerts/test` as deprecated in the OpenAPI schema (add `deprecated=True` to route decorators)
- [ ] 2.2 Verify structured logging emits WARN-level entries with `event: schwab_token_expiry` and `days_remaining: N` when token is < 7 days from expiry (add or confirm existing log statement in `app/providers/schwab.py`)

## 3. Frontend — New Shared Components

- [ ] 3.1 Create `admin/src/components/provider/ProviderDetailsPanel.tsx` — base panel with MUI `Tabs` ("Configuration" | "Authentication"), accepts `authSection: ReactNode` slot prop
- [ ] 3.2 Create `admin/src/components/provider/ProviderConfigSection.tsx` — extracts existing config form fields (Timeout, Retry, Circuit Breaker, Connection JSON) from `ProviderConfigForm` into standalone component; accepts `providerName` + callbacks
- [ ] 3.3 Create `admin/src/components/provider/ApiKeyAuthSection.tsx` — renders credential fields for a given provider from `GET /api/admin/credentials` cache; password inputs, configured/not-set chips, Save button (`PUT /api/admin/credentials/{provider}`), Test Connection button. Used for: finnhub, polygon, lseg, schwab.
- [ ] 3.4 Create `admin/src/components/provider/IbkrConnectionSection.tsx` — renders IBKR-specific connection fields (Host, Port). Reads pre-filled values from `GET /api/admin/providers/ibkr/config` → `connection_config.host` and `connection_config.port`. Saves via `PUT /api/admin/providers/ibkr/gateway`. Includes Test Connection button.

## 4. Frontend — Schwab OAuth Section

- [ ] 4.1 Create `admin/src/components/provider/SchwabOAuthSection.tsx` — shows token status (ACTIVE/EXPIRED/MISSING), days remaining, expires at; fetches from `GET /api/admin/schwab/auth/status` with query key `['schwab-status']`
- [ ] 4.2 Implement "Re-authorize" button: calls `GET /api/admin/schwab/auth/url`, opens URL in new tab via `window.open(auth_url)`
- [ ] 4.3 Implement polling logic in `SchwabOAuthSection`: after `window.open`, poll `GET /api/admin/schwab/auth/status` every 2s for max 60s; on `status: "active"` show success snackbar and stop; on timeout show error message + "Try Again" button
- [ ] 4.4 Add color coding to status display: green for ACTIVE (> 3 days), orange for ACTIVE (≤ 3 days), red for EXPIRED/MISSING

## 5. Frontend — Provider Details Integration

- [ ] 5.1 Refactor `ProvidersPage.tsx`: replace `ProviderConfigForm` usage with `ProviderDetailsPanel` that receives `ProviderConfigSection` + appropriate auth section based on provider type
- [ ] 5.2 Implement auth section routing in `ProviderSection`: 
  - `schwab` → `<><ApiKeyAuthSection providerName="schwab" /><SchwabOAuthSection /></>` (stacked)
  - `ibkr` → `<IbkrConnectionSection />` (host/port, no API keys)
  - default (finnhub, polygon, lseg) → `<ApiKeyAuthSection providerName={provider.name} />`
- [ ] 5.3 Verify accordion expand/collapse still works correctly with the new tabbed layout inside `AccordionDetails`

## 6. Frontend — Provider Filter Chips

- [ ] 6.1 Add filter chip state to `ProvidersPage.tsx`: `useState<Set<string>>` for active filter keys (`'all'`, `'active'`, `'inactive'`, `'healthy'`, `'not-configured'`)
- [ ] 6.2 Render MUI `Chip` row above provider list with: All, Active, Inactive, Healthy, Not Configured
- [ ] 6.3 Implement `filterProviders(providers, activeFilters, credentials)` pure function that applies client-side filtering logic
- [ ] 6.4 "Not Configured" filter requires credential metadata — ensure `GET /api/admin/credentials` is fetched on `ProvidersPage` and joined with provider list for filter evaluation
- [ ] 6.5 Render "No providers match the selected filters" empty state when filter result is empty

## 7. Frontend — Navigation Cleanup

- [ ] 7.1 Remove `CredentialsPage.tsx` from `admin/src/pages/`
- [ ] 7.2 Remove `SchwabAuthPage.tsx` from `admin/src/pages/`
- [ ] 7.3 Remove `AlertsPage.tsx` from `admin/src/pages/`
- [ ] 7.4 Update `admin/src/layout/Sidebar.tsx`: remove menu items Credentials, Schwab Auth, Alerts; keep Dashboard, Providers, Settings
- [ ] 7.5 Update `admin/src/router.tsx`: remove routes `/admin/credentials`, `/admin/schwab-auth`, `/admin/alerts`; add redirect or 404 for old paths
- [ ] 7.6 Update `admin/src/types.ts`: add any new TypeScript interfaces needed (`SchwabAuthStatus`, `AuthConfigType`, etc.)

## 8. Frontend — Dashboard Schwab Alert Update

- [ ] 8.1 Update `DashboardPage.tsx` Schwab expiry alert: change "Re-authorize" button navigation target from `/admin/schwab-auth` to `/admin/providers` (user expands Schwab accordion manually, or add `?expand=schwab` query param)
- [ ] 8.2 Optionally: implement `?expand=schwab` URL param handling in `ProvidersPage` to auto-expand the Schwab accordion on load

## 9. Testing & Verification

- [ ] 9.1 Run `uv run ruff check app/` — ensure no lint errors in backend changes
- [ ] 9.2 Run `uv run pytest --maxfail=1 --disable-warnings` — ensure all existing tests pass
- [ ] 9.3 Manual smoke test: configure LSEG API key via Provider Details → Authentication tab
- [ ] 9.4 Manual smoke test: configure IBKR Gateway host/port via Provider Details → Authentication tab (`IbkrConnectionSection`)
- [ ] 9.5 Manual smoke test: Schwab Re-authorize flow — click button, complete OAuth, verify token status updates automatically
- [ ] 9.6 Manual smoke test: Provider filter chips — verify each filter shows correct subset
- [ ] 9.7 Verify navigation shows exactly 3 items (Dashboard, Providers, Settings)
- [ ] 9.8 Verify `/admin/credentials`, `/admin/schwab-auth`, `/admin/alerts` redirect or 404
