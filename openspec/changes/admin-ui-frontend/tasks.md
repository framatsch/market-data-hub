## 1. Vite + React Project Setup

- [x] 1.1 Initialize Vite + React + TypeScript project in `admin/` directory: `npm create vite@latest admin -- --template react-ts`
- [x] 1.2 Install runtime dependencies: `react-router-dom @tanstack/react-query @mui/material @mui/icons-material @emotion/react @emotion/styled`
- [x] 1.3 Use Material UI styling only: custom theme + `sx` props + MUI layout/components
- [x] 1.4 Create `admin/src/theme.ts`: custom MDH Material UI theme (palette, typography, shape, component defaults)
- [x] 1.5 Wrap app in MUI `ThemeProvider` and `CssBaseline` in `main.tsx`
- [x] 1.6 Configure `vite.config.ts`: set `base: "/admin/"`, add `/api` proxy to `http://localhost:8000`
- [x] 1.7 Add `admin/dist/` and `admin/node_modules/` to root `.gitignore`
- [x] 1.8 Verify `npm run build` produces `admin/dist/index.html` and assets

## 2. App Shell & Routing

- [x] 2.1 Create `admin/src/main.tsx`: `RouterProvider` with `createBrowserRouter`, base path `/admin`
- [x] 2.2 Create `admin/src/router.tsx`: define all routes (`/admin`, `/admin/providers`, `/admin/credentials`, `/admin/schwab-auth`, `/admin/alerts`, `/admin/callback`)
- [x] 2.3 Create `admin/src/layout/AdminLayout.tsx`: Material UI `AppBar`, `Drawer`, nav links, `<Outlet />` for page content
- [x] 2.4 Create `admin/src/layout/Sidebar.tsx`: Material UI `List`, `ListItemButton`, icons, active link highlighting via `useMatch`
- [x] 2.5 Create `admin/src/lib/queryClient.ts`: TanStack Query `QueryClient` instance with sensible defaults (`staleTime: 30s`, `retry: 1`)
- [x] 2.6 Wrap app in `QueryClientProvider` in `main.tsx`

## 3. Auth Guard & OIDC Callback

- [x] 3.1 Create `admin/src/hooks/useAuth.ts`: calls `GET /api/admin/auth/me` via TanStack Query, returns `{ user, authEnabled, isLoading, isError }`
- [x] 3.2 Create `admin/src/components/AuthGuard.tsx`: renders children when authenticated or auth disabled; on 401 generates PKCE verifier/challenge, stores verifier in sessionStorage, calls `GET /api/admin/auth/url?code_challenge=...`, then redirects to returned OIDC URL; shows loading spinner during check
- [x] 3.3 Create `admin/src/lib/pkce.ts`: helper functions `generateCodeVerifier()`, `generateCodeChallenge(verifier)` using `crypto.subtle`
- [x] 3.4 Create `admin/src/pages/AuthCallbackPage.tsx`: reads `?code=` from URL, retrieves `code_verifier` from sessionStorage, calls `POST /api/admin/auth/token`, stores token in sessionStorage, redirects to `/admin`
- [x] 3.5 Handle missing `code_verifier` in `AuthCallbackPage`: show error with "Try again" button that generates a new PKCE verifier/challenge, calls `GET /api/admin/auth/url?code_challenge=...`, and redirects
- [x] 3.6 Create `admin/src/lib/api.ts`: base `fetcher` that injects `Authorization: Bearer <token>` from sessionStorage on every request

## 4. Dashboard Page

- [x] 4.1 Create `admin/src/pages/DashboardPage.tsx`: fetch `GET /api/admin/providers` with `refetchInterval: 30000`
- [x] 4.2 Render a Material UI `Card` per provider: name, `Chip` status (success=healthy, warning=paused/degraded, error=offline, default=disabled), enabled state, and config summary (`timeout_seconds`, `retry_count`, `rate_limit_per_sec`)
- [x] 4.3 Add Schwab token status banner at top using MUI `Alert`: fetch `GET /api/admin/schwab/auth/status`; show warning with "Re-authorize" CTA when `status === "expired"` or `paused === true`
- [x] 4.4 Show days remaining badge on Schwab card (e.g. "5 days left") when token is active
- [x] 4.5 Handle loading skeleton and error state for provider fetch

## 5. Providers Page

- [x] 5.1 Create `admin/src/pages/ProvidersPage.tsx`: fetch `GET /api/admin/providers`, render Material UI cards/accordion rows with enable/disable `Switch` per provider
- [x] 5.2 Implement toggle: call `POST /api/admin/providers/{name}/enable|disable`; optimistic update; rollback and show MUI `Snackbar` on error
- [x] 5.3 For each provider, fetch `GET /api/admin/providers/{name}/config` when its config panel opens
- [x] 5.4 Add provider runtime config form fields: `timeout_seconds`, `retry_count`, `retry_backoff_seconds`, `rate_limit_per_sec`, `circuit_breaker_enabled`, `circuit_breaker_failure_threshold`, `circuit_breaker_reset_seconds`
- [x] 5.5 Submit runtime config via `PUT /api/admin/providers/{name}/config`; invalidate `providers` and `providerConfig:<name>` queries on success
- [x] 5.6 Add provider-specific connection config section; for IBKR include host + port fields stored under `connection_config` (or use compatibility shortcut `PUT /api/admin/providers/ibkr/gateway` if implemented first)
- [x] 5.7 Validate numeric fields client-side before submit (positive timeout, non-negative retries, positive rate limit, positive breaker reset seconds)

## 6. Credentials Page

- [x] 6.1 Create `admin/src/pages/CredentialsPage.tsx`: fetch `GET /api/admin/credentials`, group fields by provider
- [x] 6.2 Render each provider group as a Material UI `Accordion`: show credential names with configured/unconfigured `Chip`; never display secret values
- [x] 6.3 Edit mode: expand inline Material UI form with empty password fields per key; leaving a field blank means "do not update"; "Save" and "Cancel" buttons
- [x] 6.4 On save: call `PUT /api/admin/credentials/{provider}` with changed values; show success toast; show validation error inline on 400
- [x] 6.5 Refetch credentials after successful save to reflect configured/unconfigured metadata

## 7. Schwab Auth Page

- [x] 7.1 Create `admin/src/pages/SchwabAuthPage.tsx`: fetch `GET /api/admin/schwab/auth/status` to show current token state
- [x] 7.2 Step 1 — Get Auth URL: "Generate Authorization URL" button calls `GET /api/admin/schwab/auth/url`; display the URL in a read-only input with a "Copy" button and an "Open in Browser" link; clear instructions explaining the manual step
- [x] 7.3 Step 2 — Paste Callback URL: textarea labeled "Paste the full redirect URL from your browser"; "Complete Authorization" button calls `POST /api/admin/schwab/auth/callback`
- [x] 7.4 On success: show MUI `Alert` success with new `token_expires_at` date; refetch status
- [x] 7.5 On error: show MUI `Alert` error with `detail` message from API response
- [x] 7.6 Visual MUI `Stepper` (Step 1 / Step 2) so the workflow is unambiguous

## 8. Alerts Page

- [x] 8.1 Create `admin/src/pages/AlertsPage.tsx`: fetch current webhook metadata through `GET /api/admin/credentials` (credential `schwab.alert_webhook_url`) or dedicated alerts endpoint if backend exposes one
- [x] 8.2 Webhook URL input field + MUI `Select` format selector (Slack / Generic JSON) + "Save" button calling `PUT /api/admin/alerts/webhook`
- [x] 8.3 "Send Test Alert" button: calls `POST /api/admin/alerts/test`; show success/error MUI `Snackbar`
- [x] 8.4 Show placeholder message if no webhook is configured: "Configure a webhook to receive Schwab token expiry notifications"

## 9. Build Integration & README

- [x] 9.1 Verify `npm run build` in `admin/` produces `dist/` with correct asset paths under `/admin/`
- [x] 9.2 Confirm Dockerfile multi-stage build copies `admin/dist/` to `app/static/admin/` correctly (build stage from `admin-ui-backend`)
- [x] 9.3 Run `docker build -t market-data-hub:admin-ui .` and verify `GET /admin` returns the SPA from the container
- [x] 9.4 Verify deep-link `GET /admin/providers` returns `index.html` and React Router renders the Providers page
- [x] 9.5 Update `README.md`: add Admin UI section with access URL, dev setup (`npm run dev`), auth configuration steps
