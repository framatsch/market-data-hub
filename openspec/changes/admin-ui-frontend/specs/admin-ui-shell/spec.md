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
The SPA SHALL provide a left sidebar navigation with the following top-level pages: Dashboard, Providers, Credentials, Schwab Auth, Alerts. The active page SHALL be visually indicated.

#### Scenario: Navigation between pages
- **WHEN** user clicks "Providers" in the sidebar
- **THEN** the URL changes to `/admin/providers` and the Providers page renders without full page reload

#### Scenario: Active nav item highlighted
- **WHEN** the current URL is `/admin/credentials`
- **THEN** the "Credentials" nav item is visually distinct from inactive items

### Requirement: Auth guard redirects unauthenticated users
When `ADMIN_AUTH_ENABLED=true`, the SPA SHALL check authentication state on load by calling `GET /api/admin/auth/me`. If the response is 401, the SPA SHALL redirect to the OIDC authorization URL.

#### Scenario: Unauthenticated access with auth enabled
- **WHEN** `ADMIN_AUTH_ENABLED=true` and user has no valid token
- **THEN** `GET /api/admin/auth/me` returns 401 and browser redirects to Authentik login

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
