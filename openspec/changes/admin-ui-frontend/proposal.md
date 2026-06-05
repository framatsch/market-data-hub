## Why

The `admin-ui-backend` change delivers all `/api/admin/*` endpoints and the FastAPI StaticFiles mount, but the admin interface itself has no UI. This change builds the React SPA that makes all backend capabilities accessible through a browser: provider status dashboard, credential management, Schwab OAuth2 re-authorization, and alert configuration. The frontend is built independently once the backend is complete and deployed.

## What Changes

- New `admin/` directory: Vite + React + TypeScript project at the project root
- React SPA compiled to `admin/dist/`, copied into `app/static/admin/` by the Dockerfile multi-stage build (build stage added by `admin-ui-backend`)
- OIDC auth guard: calls `GET /api/admin/auth/me`, redirects to Authentik if 401 (bypassed when auth disabled)
- PKCE authorization code flow handled entirely in the SPA (`/admin/callback` route)
- Dashboard page: live provider status cards with 30-second auto-refresh
- Providers page: enable/disable toggles + IBKR gateway URL form
- Credentials page: masked credential display with per-provider edit forms
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
- **New dev dependencies**: React, Vite, React Router v6, TanStack Query, Tailwind CSS, shadcn/ui
- **No changes** to `app/` Python code — consumes existing `/api/admin/*` endpoints only
- **Prerequisite**: `admin-ui-backend` change must be complete and deployed
