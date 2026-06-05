## Context

The backend (`admin-ui-backend`) is complete: all `/api/admin/*` endpoints exist, `app/static/admin/` is mounted as StaticFiles, and the Dockerfile has a Node build stage. This change produces the React SPA that fills that static directory.

The SPA is a pure consumer of the existing backend API — no Python changes are needed. It is built with `npm run build` inside `admin/`, producing `admin/dist/`. The Dockerfile copies that output to `app/static/admin/` at build time.

For local development, the Vite dev server runs on port 5173 and proxies all `/api/*` requests to FastAPI on port 8000 — no CORS configuration changes needed.

## Goals / Non-Goals

**Goals:**
- Complete React SPA with all five pages (Dashboard, Providers, Credentials, Schwab Auth, Alerts)
- OIDC auth guard + PKCE callback page
- All API calls via TanStack Query (loading states, error handling, auto-refresh)
- Vite dev server with `/api` proxy for local development
- Build output in `admin/dist/` compatible with the existing Dockerfile stage

**Non-Goals:**
- Backend API changes (all endpoints are delivered by `admin-ui-backend`)
- Mobile-optimized layout
- Dark mode
- Unit tests for React components (integration tested via the running app)

## Decisions

### D1: Vite + React + TypeScript
Fast dev experience, zero-config TypeScript support, optimized production build. `vite.config.ts` sets `base: "/admin/"` so all asset paths are correct when served from FastAPI's `/admin` mount.

### D2: React Router v6 for client-side routing
Handles `/admin/*` routes client-side. The catch-all route in FastAPI (`GET /admin/{path}` → `index.html`) ensures deep-links work.

### D3: TanStack Query for server state
Handles caching, background refetch, loading/error states for all API calls. Provider status auto-refreshes every 30 seconds via `refetchInterval`. Eliminates manual `useEffect`/fetch boilerplate.

### D4: shadcn/ui + Tailwind CSS
shadcn/ui generates component source files (no runtime package dependency). Tailwind handles styling. Together they produce a clean, maintainable UI without a heavyweight framework.

### D5: Access token stored in sessionStorage
Pragmatic trade-off for an admin tool. Not localStorage (persists across tabs indefinitely — worse security surface). Not memory-only (lost on page refresh, forces re-auth on every reload). sessionStorage is tab-scoped and cleared when the tab closes.

### D6: Vite proxy for local dev
`vite.config.ts` proxies `/api` → `http://localhost:8000`. Developers run `python -m app.main` and `npm run dev` simultaneously. No CORS headers needed in FastAPI for development.

## Risks / Trade-offs

- **`admin/dist/` not committed** → CI must run `npm ci && npm run build` before Docker build. The Dockerfile build stage handles this automatically. Local dev uses Vite dev server, not the built assets.
- **PKCE code verifier in sessionStorage** → If the browser tab is closed between step 1 (auth URL) and step 2 (callback), the verifier is lost and auth fails. Mitigation: show a clear error on the callback page with a "Try again" button.
- **TanStack Query cache** → stale provider status may show briefly after enable/disable. Mitigation: invalidate the providers query cache immediately on mutation success.

## Migration Plan

1. Ensure `admin-ui-backend` is deployed and `GET /api/admin/providers` responds
2. Run `npm create vite@latest admin -- --template react-ts` from project root
3. Implement pages iteratively — each page is independently functional
4. Run `npm run build` and verify `app/static/admin/` is populated after Docker build
5. Verify `GET /admin` serves the SPA from the running container

## Open Questions

- (none — all design decisions are resolved; backend API contract is fixed by `admin-ui-backend`)
