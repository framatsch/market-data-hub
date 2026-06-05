## 1. Vite + React Project Setup

- [ ] 1.1 Initialize Vite + React + TypeScript project in `admin/` directory: `npm create vite@latest admin -- --template react-ts`
- [ ] 1.2 Install runtime dependencies: `react-router-dom @tanstack/react-query`
- [ ] 1.3 Install dev/styling dependencies: `tailwindcss @tailwindcss/vite`
- [ ] 1.4 Install shadcn/ui: `npx shadcn@latest init` — choose default style, Tailwind CSS variables
- [ ] 1.5 Add shadcn/ui components used by the app: `npx shadcn@latest add button card badge input label switch toast`
- [ ] 1.6 Configure `vite.config.ts`: set `base: "/admin/"`, add `/api` proxy to `http://localhost:8000`
- [ ] 1.7 Add `admin/dist/` and `admin/node_modules/` to root `.gitignore`
- [ ] 1.8 Verify `npm run build` produces `admin/dist/index.html` and assets

## 2. App Shell & Routing

- [ ] 2.1 Create `admin/src/main.tsx`: `RouterProvider` with `createBrowserRouter`, base path `/admin`
- [ ] 2.2 Create `admin/src/router.tsx`: define all routes (`/admin`, `/admin/providers`, `/admin/credentials`, `/admin/schwab-auth`, `/admin/alerts`, `/admin/callback`)
- [ ] 2.3 Create `admin/src/layout/AdminLayout.tsx`: sidebar with nav links, `<Outlet />` for page content
- [ ] 2.4 Create `admin/src/layout/Sidebar.tsx`: nav items (Dashboard, Providers, Credentials, Schwab Auth, Alerts) with active link highlighting via `useMatch`
- [ ] 2.5 Create `admin/src/lib/queryClient.ts`: TanStack Query `QueryClient` instance with sensible defaults (`staleTime: 30s`, `retry: 1`)
- [ ] 2.6 Wrap app in `QueryClientProvider` in `main.tsx`

## 3. Auth Guard & OIDC Callback

- [ ] 3.1 Create `admin/src/hooks/useAuth.ts`: calls `GET /api/admin/auth/me` via TanStack Query, returns `{ user, authEnabled, isLoading, isError }`
- [ ] 3.2 Create `admin/src/components/AuthGuard.tsx`: renders children when authenticated or auth disabled; redirects to OIDC URL when 401 and auth enabled; shows loading spinner during check
- [ ] 3.3 Create `admin/src/lib/pkce.ts`: helper functions `generateCodeVerifier()`, `generateCodeChallenge(verifier)` using `crypto.subtle`
- [ ] 3.4 Create `admin/src/pages/AuthCallbackPage.tsx`: reads `?code=` from URL, retrieves `code_verifier` from sessionStorage, calls `POST /api/admin/auth/token`, stores token in sessionStorage, redirects to `/admin`
- [ ] 3.5 Handle missing `code_verifier` in `AuthCallbackPage`: show error with "Try again" button that calls `GET /api/admin/auth/url` and redirects
- [ ] 3.6 Create `admin/src/lib/api.ts`: base `fetcher` that injects `Authorization: Bearer <token>` from sessionStorage on every request

## 4. Dashboard Page

- [ ] 4.1 Create `admin/src/pages/DashboardPage.tsx`: fetch `GET /api/admin/providers` with `refetchInterval: 30000`
- [ ] 4.2 Render a status card per provider: name, colored badge (green=healthy, yellow=paused, orange=degraded, red=offline, grey=disabled)
- [ ] 4.3 Add Schwab token status banner at top: fetch `GET /api/admin/schwab/auth/status`; show warning banner with "Re-authorize" CTA when `status === "expired"` or `paused === true`
- [ ] 4.4 Show days remaining badge on Schwab card (e.g. "5 days left") when token is active
- [ ] 4.5 Handle loading skeleton and error state for provider fetch

## 5. Providers Page

- [ ] 5.1 Create `admin/src/pages/ProvidersPage.tsx`: fetch `GET /api/admin/providers`, render list with enable/disable `Switch` per provider
- [ ] 5.2 Implement toggle: call `POST /api/admin/providers/{name}/enable|disable` on switch change; optimistic update; rollback and show toast on error
- [ ] 5.3 Add IBKR gateway section: text inputs for host + port, "Save" button calls `PUT /api/admin/providers/ibkr/gateway`; show current values from providers response
- [ ] 5.4 Invalidate providers query cache on successful mutation so Dashboard updates immediately

## 6. Credentials Page

- [ ] 6.1 Create `admin/src/pages/CredentialsPage.tsx`: fetch `GET /api/admin/credentials`, group fields by provider
- [ ] 6.2 Render each provider group as a collapsible card: show credential keys with masked values, "Edit" button per group
- [ ] 6.3 Edit mode: expand inline form with input fields per key (password input type for secrets), "Save" and "Cancel" buttons
- [ ] 6.4 On save: call `PUT /api/admin/credentials/{provider}` with changed values; show success toast; show validation error inline on 400
- [ ] 6.5 Refetch credentials after successful save to reflect new masked values

## 7. Schwab Auth Page

- [ ] 7.1 Create `admin/src/pages/SchwabAuthPage.tsx`: fetch `GET /api/admin/schwab/auth/status` to show current token state
- [ ] 7.2 Step 1 — Get Auth URL: "Generate Authorization URL" button calls `GET /api/admin/schwab/auth/url`; display the URL in a read-only input with a "Copy" button and an "Open in Browser" link; clear instructions explaining the manual step
- [ ] 7.3 Step 2 — Paste Callback URL: textarea labeled "Paste the full redirect URL from your browser"; "Complete Authorization" button calls `POST /api/admin/schwab/auth/callback`
- [ ] 7.4 On success: show green confirmation card with new `token_expires_at` date; refetch status
- [ ] 7.5 On error: show red error card with `detail` message from API response
- [ ] 7.6 Visual step indicator (Step 1 / Step 2) so the workflow is unambiguous

## 8. Alerts Page

- [ ] 8.1 Create `admin/src/pages/AlertsPage.tsx`: fetch `GET /api/admin/credentials` to show current `SCHWAB_ALERT_WEBHOOK_URL`
- [ ] 8.2 Webhook URL input field + format selector (Slack / Generic JSON) + "Save" button calling `PUT /api/admin/credentials/schwab` for the webhook fields
- [ ] 8.3 "Send Test Alert" button: calls `POST /api/admin/alerts/test`; show success/error toast
- [ ] 8.4 Show placeholder message if no webhook is configured: "Configure a webhook to receive Schwab token expiry notifications"

## 9. Build Integration & README

- [ ] 9.1 Verify `npm run build` in `admin/` produces `dist/` with correct asset paths under `/admin/`
- [ ] 9.2 Confirm Dockerfile multi-stage build copies `admin/dist/` to `app/static/admin/` correctly (build stage from `admin-ui-backend`)
- [ ] 9.3 Run `docker build -t market-data-hub:admin-ui .` and verify `GET /admin` returns the SPA from the container
- [ ] 9.4 Verify deep-link `GET /admin/providers` returns `index.html` and React Router renders the Providers page
- [ ] 9.5 Update `README.md`: add Admin UI section with access URL, dev setup (`npm run dev`), auth configuration steps
