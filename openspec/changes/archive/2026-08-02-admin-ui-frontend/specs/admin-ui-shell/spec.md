## ADDED Requirements

### Requirement: SPA served at /admin
FastAPI SHALL mount the React build output directory (`app/static/admin/`) as StaticFiles at `/admin`. A catch-all route SHALL return `index.html` for any `/admin/{path}` that does not match a static file, enabling client-side routing. (Implementation is in `admin-ui-backend`; this spec describes the contract the frontend depends on.)

#### Scenario: Direct navigation to admin root
- **WHEN** a browser requests `GET /admin`
- **THEN** the server returns `index.html` with status 200

#### Scenario: Deep-link to admin sub-page
- **WHEN** a browser requests `GET /admin/providers`
- **THEN** the server returns `index.html`, allowing React Router to handle routing

#### Scenario: Static assets served correctly
- **WHEN** the browser requests `GET /admin/assets/index-abc123.js`
- **THEN** the server returns the JS bundle with correct `Content-Type`

### Requirement: React app navigation structure
The SPA SHALL provide a Material UI `Drawer` sidebar navigation with the following top-level pages: Dashboard, Providers, Credentials, Schwab Auth, Alerts. The active page SHALL be visually indicated using Material UI selected list item styling.

#### Scenario: Navigation between pages
- **WHEN** user clicks "Providers" in the sidebar
- **THEN** the URL changes to `/admin/providers` and the Providers page renders without full page reload

#### Scenario: Active nav item highlighted
- **WHEN** the current URL is `/admin/credentials`
- **THEN** the "Credentials" nav item is visually distinct from inactive items

### Requirement: Material UI theme
The SPA SHALL use Material UI as the component system. It SHALL define a custom MDH theme in `admin/src/theme.ts`, wrap the application in MUI `ThemeProvider`, and include MUI `CssBaseline`.

#### Scenario: Theme applied globally
- **WHEN** the SPA renders any page
- **THEN** Material UI theme tokens (palette, typography, shape, component defaults) apply consistently across cards, forms, buttons, chips, alerts, and navigation

#### Scenario: No shadcn or Tailwind dependency
- **WHEN** the frontend project is installed
- **THEN** the UI component dependencies are Material UI and Emotion; shadcn/ui and Tailwind are not required

### Requirement: Auth guard redirects unauthenticated users
When `ADMIN_AUTH_ENABLED=true`, the SPA SHALL check authentication state on load by calling `GET /api/admin/auth/me`. If the response is 401, the SPA SHALL generate a PKCE verifier/challenge pair, store the verifier in `sessionStorage`, request `GET /api/admin/auth/url?code_challenge=<challenge>`, and redirect to the returned OIDC authorization URL.

#### Scenario: Unauthenticated access with auth enabled
- **WHEN** `ADMIN_AUTH_ENABLED=true` and user has no valid token
- **THEN** `GET /api/admin/auth/me` returns 401, SPA stores a PKCE verifier, requests `/api/admin/auth/url?code_challenge=...`, and browser redirects to Authentik login

#### Scenario: Authenticated access proceeds normally
- **WHEN** `ADMIN_AUTH_ENABLED=true` and user has a valid Bearer token
- **THEN** `GET /api/admin/auth/me` returns 200 and admin UI renders normally

#### Scenario: Auth disabled — no redirect
- **WHEN** `ADMIN_AUTH_ENABLED=false`
- **THEN** `GET /api/admin/auth/me` returns 200 without token validation and admin UI renders immediately

### Requirement: PKCE callback page handles token exchange
The SPA SHALL provide a `/admin/callback` route that reads `code` from the URL query string, exchanges it via `POST /api/admin/auth/token` with the stored PKCE `code_verifier`, stores the returned access token in sessionStorage, and redirects to `/admin`.

#### Scenario: Successful OAuth2 callback
- **WHEN** Authentik redirects to `/admin/callback?code=abc123`
- **THEN** SPA exchanges the code, stores token, and redirects to `/admin/dashboard`

#### Scenario: Missing code verifier (tab was closed)
- **WHEN** `/admin/callback` is reached but no `code_verifier` is in sessionStorage
- **THEN** SPA shows an error message with a "Try again" button that restarts the auth flow

### Requirement: Vite dev server proxies API calls
In development mode, the Vite dev server SHALL proxy all `/api/*` requests to FastAPI at `http://localhost:8000`.

#### Scenario: API call during local development
- **WHEN** the Vite dev server is running and SPA calls `GET /api/admin/providers`
- **THEN** the request is proxied to `http://localhost:8000/api/admin/providers` transparently

### Requirement: Providers page manages backend runtime config
The Providers page SHALL align with `admin-ui-backend` provider APIs. It SHALL list providers from `GET /api/admin/providers`, allow enable/disable via `POST /api/admin/providers/{name}/enable|disable`, and expose runtime config editing via `GET` and `PUT /api/admin/providers/{name}/config`.

#### Scenario: Provider config panel loads config lazily
- **WHEN** user opens the config panel for provider "schwab"
- **THEN** SPA calls `GET /api/admin/providers/schwab/config` and populates fields for timeout, retry, rate limit, circuit breaker, and connection config

#### Scenario: Runtime config saved
- **WHEN** user edits `timeout_seconds`, `retry_count`, `rate_limit_per_sec`, and circuit-breaker fields then clicks Save
- **THEN** SPA sends `PUT /api/admin/providers/{name}/config` with those values and invalidates provider-related query caches on success

#### Scenario: IBKR connection config edited
- **WHEN** user edits IBKR host and port
- **THEN** SPA sends the values as provider-specific `connection_config` through `PUT /api/admin/providers/ibkr/config` or uses `PUT /api/admin/providers/ibkr/gateway` compatibility endpoint if that is the implemented backend path

#### Scenario: Invalid numeric input blocked client-side
- **WHEN** user enters a negative timeout or negative retry count
- **THEN** Save is disabled or validation feedback is shown before an API request is sent

### Requirement: Credentials page matches encrypted SQLite metadata model
The Credentials page SHALL never expect plaintext credential values from the backend. It SHALL render configured/unconfigured metadata from `GET /api/admin/credentials` and submit changed plaintext values only through `PUT /api/admin/credentials/{provider}`.

#### Scenario: Configured credential displayed without value
- **WHEN** backend returns `{"provider": "finnhub", "credential_name": "api_key", "set": true, "masked_value": "configured"}`
- **THEN** UI shows Finnhub API key as configured without displaying any secret characters

#### Scenario: Blank credential field does not overwrite
- **WHEN** user opens edit mode and leaves a credential input blank
- **THEN** the frontend omits that credential from the update payload

### Requirement: Alerts page uses alerts endpoints
The Alerts page SHALL save webhook settings through `PUT /api/admin/alerts/webhook` and test delivery through `POST /api/admin/alerts/test`. It SHALL not write webhook settings through the generic credentials endpoint.

#### Scenario: Webhook saved through alerts endpoint
- **WHEN** user enters webhook URL and format then clicks Save
- **THEN** SPA calls `PUT /api/admin/alerts/webhook`

#### Scenario: Test alert sent
- **WHEN** user clicks "Send Test Alert"
- **THEN** SPA calls `POST /api/admin/alerts/test` and shows success/error feedback using Material UI `Snackbar` or `Alert`
