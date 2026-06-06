## 1. Backend — Schwab OAuth Automatic Callback

- [ ] 1.1 Add in-memory state store in `app/api/routes_admin.py`: `_schwab_pending_states: dict[str, tuple[AuthContext, datetime]]` and `_schwab_callback_error: dict[str, tuple[str, datetime]]`
- [ ] 1.2 Update `GET /api/admin/schwab/auth/url`: replace direct URL construction with `schwab.auth.get_auth_context(api_key, callback_url=settings.SCHWAB_CALLBACK_URL)`, store `(auth_context, now())` in `_schwab_pending_states`, evict entries older than 10 min, return `{"auth_url": auth_context.authorization_url}`
- [ ] 1.3 Add **unauthenticated** `GET /api/admin/schwab/callback` endpoint (no `PrincipalDep`): accepts `code: str` and `state: str` query params
- [ ] 1.4 In the callback endpoint: validate `state` against `_schwab_pending_states` (reject if missing/expired → write to `_schwab_callback_error` → return HTML 400 error page)
- [ ] 1.5 On valid state: call `client_from_received_url(api_key, app_secret, auth_context=stored_auth_context, received_url=str(request.url), token_write_func=...)`, save `token_json`, unpause provider, clear `_schwab_callback_error`; return HTML 200 success page
- [ ] 1.6 On token exchange exception: write `(str(exc), now())` to `_schwab_callback_error`, return HTML 400 error page
- [ ] 1.7 Update `GET /api/admin/schwab/auth/status`: check `_schwab_callback_error` for recent errors (< 5 min); if found, return `{"status": "callback_error", "error": "...", "paused": true}`
- [ ] 1.8 Mark existing `POST /api/admin/schwab/auth/callback` as deprecated (`deprecated=True` on router decorator); add note in docstring; do NOT remove yet

## 2. Backend — IBKR Gateway Update Extended

- [ ] 2.1 Extend `IbkrGatewayUpdate` Pydantic model in `routes_admin.py` to accept all 6 fields: `host: str`, `port: int`, `client_id: int | None = None`, `account_id: str | None = None`, `env: Literal["live", "paper"] | None = None`, `market_data_type: int | None = None`
- [ ] 2.2 Update `update_ibkr_gateway` handler to merge all provided (non-None) fields into `connection_config` (partial update — omitted fields preserved)
- [ ] 2.3 Update `SCHWAB_CALLBACK_URL` default in `app/config.py` from `https://127.0.0.1:8182` to `http://localhost:8000/api/admin/schwab/callback`

## 3. Backend — Cleanup Alerts Endpoints

- [ ] 3.1 Mark `GET /api/admin/alerts/webhook`, `PUT /api/admin/alerts/webhook`, `POST /api/admin/alerts/test` as deprecated (`deprecated=True` on route decorators)
- [ ] 3.2 Verify structured logging emits WARN-level log entries with `event: schwab_token_expiry` and `days_remaining: N` when token is near expiry (confirm or add to `app/providers/schwab.py`)

## 4. Frontend — New Shared Components

- [ ] 4.1 Create `admin/src/components/provider/ProviderDetailsPanel.tsx` — base panel with MUI `Tabs` ("Configuration" | "Connection / Auth"), accepts `authSection: ReactNode` slot prop and `hideConnectionJson?: boolean` prop
- [ ] 4.2 Create `admin/src/components/provider/ProviderConfigSection.tsx` — extracts config form fields (Timeout, Retry, Circuit Breaker, Connection JSON textarea); when `hideConnectionJson={true}`, suppresses the JSON textarea; accepts `providerName` + callbacks
- [ ] 4.3 Create `admin/src/components/provider/ApiKeyAuthSection.tsx` — renders credential fields from `GET /api/admin/credentials` cache with key `['credentials']`; accepts optional `visibleCredentials?: string[]` prop to filter shown fields; password inputs, configured/not-set chips, "Save Credentials" button (omits blank fields from payload), Test Connection button

## 5. Frontend — IBKR Connection Section

- [ ] 5.1 Create `admin/src/components/provider/IbkrConnectionSection.tsx` — renders 6 fields: host (text), port (number), client_id (number), account_id (text), env (Select: live/paper), market_data_type (Select: 1/2/3/4 with labels); pre-fills from `GET /api/admin/providers/ibkr/config` → `connection_config`
- [ ] 5.2 "Save" button calls `PUT /api/admin/providers/ibkr/gateway` with all 6 fields; shows success snackbar "IBKR gateway connection updated"
- [ ] 5.3 "Test Connection" button calls `POST /api/admin/test-connection/ibkr`, shows inline result

## 6. Frontend — Schwab OAuth Section

- [ ] 6.1 Create `admin/src/components/provider/SchwabOAuthSection.tsx` — fetches from `GET /api/admin/schwab/auth/status` with React Query key `['schwab', 'status']`; displays status (ACTIVE/EXPIRED/NOT_CONFIGURED/CALLBACK_ERROR), days remaining, expires at with color coding (green >3d, orange ≤3d, red otherwise)
- [ ] 6.2 "Re-authorize" button: calls `GET /api/admin/schwab/auth/url`, opens returned URL with `window.open(auth_url)`, enters "Waiting for authorization..." state with spinner
- [ ] 6.3 Polling: after `window.open`, poll `['schwab', 'status']` every 2s up to 60s; on `status: "active"` → success snackbar + stop; on `status: "callback_error"` → error snackbar with `error` field + stop; on timeout → "Authorization timed out or was cancelled." + "Try Again" button

## 7. Frontend — Provider Details Integration

- [ ] 7.1 Refactor `ProvidersPage.tsx`: replace `ProviderConfigForm` usage with `ProviderDetailsPanel`; pass `hideConnectionJson={provider.name === 'ibkr'}`
- [ ] 7.2 Implement auth section routing in `ProviderSection`:
  - `schwab` → `<><ApiKeyAuthSection providerName="schwab" visibleCredentials={["api_key", "app_secret"]} /><SchwabOAuthSection /></>`
  - `ibkr` → `<IbkrConnectionSection />`
  - default → `<ApiKeyAuthSection providerName={provider.name} />`
- [ ] 7.3 Verify accordion expand/collapse still works correctly with the new tabbed layout inside `AccordionDetails`

## 8. Frontend — Provider Filter Chips

- [ ] 8.1 Add filter state to `ProvidersPage.tsx`: `useState<Set<string>>` with keys `'all'|'active'|'inactive'|'healthy'|'not-configured'`
- [ ] 8.2 Render MUI `Chip` row above provider list: All, Active, Inactive, Healthy, Not Configured
- [ ] 8.3 Implement `filterProviders(providers, activeFilters, credentials)` pure function:
  - `active`: `provider.enabled === true`
  - `inactive`: `provider.enabled === false`
  - `healthy`: `provider.status === "healthy"`
  - `not-configured`: finnhub/polygon/lseg/schwab → all credentials `set: false`; ibkr → `connection_config.account_id === "DU123456"`; mock/prixe → never match
- [ ] 8.4 Fetch `GET /api/admin/credentials` on `ProvidersPage` (key `['credentials']`) for "Not Configured" filter evaluation
- [ ] 8.5 Render "No providers match the selected filters" empty state when filter result is empty

## 9. Frontend — Navigation Cleanup + Auto-Expand

- [ ] 9.1 Remove `CredentialsPage.tsx`, `SchwabAuthPage.tsx`, `AlertsPage.tsx` from `admin/src/pages/`
- [ ] 9.2 Update `admin/src/layout/Sidebar.tsx`: keep only Dashboard, Providers, Settings
- [ ] 9.3 Update `admin/src/router.tsx`: remove routes `/admin/credentials`, `/admin/schwab-auth`, `/admin/alerts`; add redirect or 404 for old paths
- [ ] 9.4 Update `admin/src/types.ts`: add `SchwabAuthStatus` interface (`status`, `paused`, `days_remaining?`, `expires_at?`, `error?`); update `Provider` to include `connection_config`
- [ ] 9.5 Implement `?expand=<provider_name>` in `ProvidersPage`: read `useSearchParams()` on mount; if `expand` param is set, auto-expand that provider's accordion and activate the "Connection / Auth" tab

## 10. Frontend — Dashboard Schwab Alert Update

- [ ] 10.1 Update `DashboardPage.tsx` Schwab expiry alert: change "Re-authorize" button navigation target to `/admin/providers?expand=schwab`

## 11. Testing & Verification

- [ ] 11.1 Run `uv run ruff check app/` — ensure no lint errors in backend changes
- [ ] 11.2 Run `uv run pytest --maxfail=1 --disable-warnings` — ensure all existing tests pass
- [ ] 11.3 Manual smoke test: configure LSEG API key via Providers → expand LSEG → Connection / Auth tab → enter key → Save
- [ ] 11.4 Manual smoke test: configure IBKR host/port/client_id via Providers → expand IBKR → Connection / Auth tab → all 6 fields pre-filled → edit and Save
- [ ] 11.5 Manual smoke test: Schwab Re-authorize — click "Re-authorize", complete OAuth in new tab, verify polling detects `status: "active"` and shows success snackbar
- [ ] 11.6 Manual smoke test: Schwab Re-authorize error — use invalid credentials, verify polling detects `status: "callback_error"` and shows error snackbar (no 60s wait)
- [ ] 11.7 Manual smoke test: Dashboard Schwab alert "Re-authorize" → navigates to `/admin/providers?expand=schwab` → Schwab accordion auto-expanded with "Connection / Auth" tab active
- [ ] 11.8 Manual smoke test: Provider filter chips — verify each filter shows correct subset; verify IBKR "Not Configured" triggers on `account_id=DU123456`
- [ ] 11.9 Verify navigation shows exactly 3 items (Dashboard, Providers, Settings)
- [ ] 11.10 Verify `/admin/credentials`, `/admin/schwab-auth`, `/admin/alerts` redirect or 404
