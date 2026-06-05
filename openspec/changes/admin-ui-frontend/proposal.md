## Why

The `admin-ui-backend` change delivers all `/api/admin/*` endpoints and the FastAPI StaticFiles mount, but the admin interface itself has no UI. This change builds the React SPA that makes all backend capabilities accessible through a browser: provider status dashboard, credential management, Schwab OAuth2 re-authorization, and alert configuration. The frontend is built independently once the backend is complete and deployed.

## What Changes

- New `admin/` directory: Vite + React + TypeScript project at the project root
- React SPA compiled to `admin/dist/`, copied into `app/static/admin/` by the Dockerfile multi-stage build (build stage added by `admin-ui-backend`)
- OIDC auth guard: calls `GET /api/admin/auth/me`, redirects to Authentik if 401 (bypassed when auth disabled)
- PKCE authorization code flow handled entirely in the SPA (`/admin/callback` route)
- Dashboard page: live provider status cards with 30-second auto-refresh
- Providers page: enable/disable toggles plus provider runtime configuration forms for timeout, retry, rate limit, circuit breaker, and provider-specific connection config (e.g. IBKR host/port)
- Credentials page: configured/unconfigured credential metadata display with per-provider edit forms; plaintext values are never read back from backend
- Schwab Auth page: step-by-step OAuth2 re-authorization UI (get URL → paste callback URL → confirm)
- Alerts page: webhook URL configuration + test send

## Capabilities

### New Capabilities

- `admin-ui-shell`: React SPA shell — Vite project setup, routing, OIDC auth guard, sidebar navigation layout, served at `/admin`

### Modified Capabilities

- (none — all backend capabilities were specified in `admin-ui-backend`)

## Impact

- **New files**: `admin/` directory (Vite/React project), `admin/dist/` (gitignored build output)
- **Modified files**: `.gitignore` (add `admin/dist/`), `README.md` (Admin UI section)
- **New dev/runtime dependencies**: React, Vite, React Router v6, TanStack Query, Material UI (`@mui/material`, `@mui/icons-material`, `@emotion/react`, `@emotion/styled`)
- **No changes** to `app/` Python code — consumes existing `/api/admin/*` endpoints only
- **Prerequisite**: `admin-ui-backend` change must be complete and deployed
