## Context

The admin UI has 6 navigation entries: Dashboard, Providers, Credentials, Schwab Auth, Alerts, Settings. Credentials, Schwab Auth, and Alerts are conceptually sub-aspects of provider configuration but modeled as separate pages. This causes cognitive fragmentation: to fully configure Schwab, the user switches between 3 pages.

The frontend is React 19 + TypeScript + MUI v9. Components are exclusively functional (no classes). "Inheritance" in React is achieved through composition + shared interfaces. The backend runs as FastAPI with existing endpoints for Provider Config, Credentials, and Schwab OAuth.

The current Schwab OAuth flow is manual: the user copies a URL, opens it, copies the redirect URL, and pastes it back. An automatic backend callback is technically feasible because Schwab allows `http://localhost` as a `redirect_uri`.

## Goals / Non-Goals

**Goals:**

- Reduce navigation to 3 entries: Dashboard, Providers, Settings
- Provider Details Page: Config + Auth configuration in a single expanded view
- Unified `ProviderDetailsPanel` base component shared by all providers; second tab label is "Connection / Auth" (not "Authentication")
- Three Auth Section components, depending on provider type:
  - `ApiKeyAuthSection` — editable key list (finnhub: `api_key`; polygon: `api_key`; lseg: `app_key`, `username`, `password`; Schwab: `api_key`, `app_secret` only — `token_json` and `alert_webhook_url` filtered client-side)
  - `IbkrConnectionSection` — all 6 gateway fields: `host`, `port`, `client_id`, `account_id`, `env`, `market_data_type`; JSON textarea suppressed for IBKR
  - `SchwabOAuthSection` — OAuth status + automatic re-authorization flow (Schwab, in addition to ApiKeyAuthSection)
- Chip filter on the Provider overview
- Schwab OAuth automatic: backend redirect, no copy-paste
- Alerts/Webhook completely removed (log-based monitoring via Grafana)
- Dashboard "Re-authorize" button navigates to `/admin/providers?expand=schwab` (mandatory auto-expand + tab switch)

**Non-Goals:**

- No changes to backend credential storage or Provider Registry
- No dark mode, no theming changes
- No additional OAuth providers (Schwab only)
- No changes to the Dashboard page
- No changes to existing API endpoints except the new Schwab callback endpoint

## Decisions

### D1: Composition over Class Inheritance

**React is functional** — no class components. "Inheritance" is modeled as:

```
ProviderDetailsPanel (base component)
├── Props: provider, config, authSection: ReactNode
└── Renders: Header | ConfigSection | [Connection / Auth] tab (via authSection slot)

ApiKeyAuthSection          ← finnhub, polygon, lseg, Schwab (API Keys; Schwab filtered to api_key + app_secret)
IbkrConnectionSection      ← IBKR (all 6 connection fields; JSON textarea suppressed in Config tab)
SchwabOAuthSection         ← Schwab (in addition to ApiKeyAuthSection)
```

`ProvidersPage` decides via lookup:
- `schwab` → authSection contains `ApiKeyAuthSection` (api_key + app_secret only) + `SchwabOAuthSection` (stacked)
- `ibkr` → authSection = `<IbkrConnectionSection />` (6 fields); Config tab hides JSON textarea
- all others (finnhub, polygon, lseg) → authSection = `<ApiKeyAuthSection providerName={provider.name} />`

No separate router route per provider — everything stays in the Accordion structure of `ProvidersPage`.

**Alternatives discarded:**
- Separate route `/admin/providers/:name` — over-engineering for 4-5 providers; Accordion is UX-appropriate
- Class inheritance via abstract TypeScript classes — unidiomatic in React, breaks hooks rules

---

### D2: Auth Configuration in AccordionDetails, not in Modal

Provider Details (Accordion) use **Tabs**. The second tab is labeled **"Connection / Auth"** for all providers (not "Authentication", which is semantically wrong for IBKR where the tab contains gateway connectivity settings):

```
[Provider Name ▾]
  ┌─ Enabled / Status Chip ─────────────────────────────┐
  │  Tab: Configuration | Tab: Connection / Auth         │
  │                                                       │
  │  [Configuration Tab]                                  │
  │  Timeout, Retry, Circuit Breaker                      │
  │  (Connection Config JSON hidden for IBKR)             │
  │                                                       │
  │  [Connection / Auth Tab]                              │
  │  IBKR:  Host, Port, Client ID, Account, Env, MDType  │
  │  Other: API Key Auth:  [key1] [key2]  [Save]         │
  │  Schwab: API Keys + OAuth Status  [Re-authorize]     │
  └───────────────────────────────────────────────────────┘
```

MUI `Tabs` inside `AccordionDetails` — clean, no route complexity.

**Alternatives discarded:**
- Separate route per provider — over-engineering for 4-5 providers
- All fields without tabs — AccordionDetails would become too long

---

### D3: Schwab OAuth — Automatic Backend Callback with State CSRF

The current schwab-py API requires `get_auth_context()` to generate the authorization URL. This produces an `AuthContext(callback_url, authorization_url, state)` object containing a random `state` value. The new flow uses this `state` as a CSRF guard.

**Flow:**
1. User clicks "Re-authorize" in `SchwabOAuthSection`
2. Frontend calls `GET /api/admin/schwab/auth/url` (authenticated)
3. Backend calls `schwab.auth.get_auth_context(api_key, callback_url=settings.SCHWAB_CALLBACK_URL)` — receives `AuthContext` with `authorization_url` and random `state`
4. Backend stores `(state, auth_context)` in a short-lived in-memory dict (TTL 10 minutes)
5. Backend returns `{"auth_url": auth_context.authorization_url}` to frontend
6. Frontend opens `auth_url` in a new tab: `window.open(auth_url)`
7. User logs in to Schwab, Schwab redirects to `settings.SCHWAB_CALLBACK_URL` (must be set to e.g. `http://localhost:8000/api/admin/schwab/callback`) with `?code=...&state=...`
8. New unauthenticated `GET /api/admin/schwab/callback?code=...&state=...` endpoint:
   - Validates `state` against the in-memory store; rejects unknown or expired state → writes `{status: "callback_error", error: "Invalid state"}` to a transient error store
   - Reconstructs full URL from `request.url` and calls `client_from_received_url(api_key, app_secret, auth_context=stored_auth_context, received_url=str(request.url), token_write_func=...)`
   - On success: saves `token_json`, unpauses provider, writes `{status: "active"}` state, clears error store, returns HTML "Authorization successful. You may close this tab."
   - On failure: writes `{status: "callback_error", error: str(exc)}` to transient error store (TTL 5 min), returns HTML error page
9. Original tab: `SchwabOAuthSection` polls `GET /api/admin/schwab/auth/status` every 2s for max 60s
   - `status: "active"` → show success snackbar "Schwab successfully re-authorized", stop polling
   - `status: "callback_error"` → show error snackbar with `error` message, stop polling immediately
   - Timeout after 60s with ambiguous message "Authorization timed out or was cancelled"

**`SCHWAB_CALLBACK_URL` must be updated:** The default value `https://127.0.0.1:8182` must be changed to `http://localhost:8000/api/admin/schwab/callback` (or the production equivalent). This must also match the `redirect_uri` registered in the Schwab Developer Portal.

**State storage:** Use a simple in-memory `dict[str, tuple[AuthContext, datetime]]` in `routes_admin.py`. No DB required — state is ephemeral and single-instance. Add a background cleanup to evict expired entries on each `/auth/url` call.

**Old `POST /api/admin/schwab/auth/callback` endpoint:** Keep it for one release cycle (marked deprecated) then remove it in the next version. It is no longer called by any UI component after this change.

**Why Polling over WebSocket:** Simple to implement, 60s max is acceptable for a one-time operation. The transient error store ensures polling detects failures without a WebSocket.

**Alternatives discarded:**
- Manual copy-paste (current) — poor UX
- PostMessage from popup to parent — too complex, cross-origin issues possible
- WebSocket for real-time status — over-engineering for a one-time, infrequent operation

---

### D4: Provider Filter as Client-Side State Filter

Filter chips are applied **client-side** against the loaded provider list:

```
[All]  [Active]  [Inactive]  [Healthy]  [Not Configured]
```

**"Not Configured"** heuristic differs by provider type:
- **finnhub, polygon, lseg, schwab**: all credentials from `GET /api/admin/credentials` are `set: false`
- **ibkr**: `connection_config.account_id === "DU123456"` (the placeholder default from `config.py`). Host/port defaults (127.0.0.1:4001) are valid working values for a local Gateway setup and are NOT used as the heuristic.
- **mock, prixe**: always considered configured (no credentials or connection config required)

**Multi-chip selection:** Chips are additive OR filters (a provider matches if it satisfies ANY selected filter). Selecting `Active` + `Inactive` shows all providers (same as `All`). Selecting no chips = same as `All`. The `All` chip explicitly deselects all other chips.

The filter is a `Set<string>` in local state. No API parameter, no refetch.

---

### D5: Webhook/Alerts Removed

`AlertsPage.tsx` and all associated backend endpoints (`/api/admin/alerts/*`) are removed. Schwab token expiry warnings are delegated to structured logging (already in place) via Grafana. No replacement in the UI.

**Alternatives discarded:**
- Move webhook to Settings — complexity without clear benefit; Grafana integration is more robust

---

### D6: Credentials API Format Remains Unchanged

The APIs `GET /api/admin/credentials` and `PUT /api/admin/credentials/{provider}` are consumed unchanged. IBKR has NO entries in `CREDENTIAL_ALLOWLIST` (see `routes_admin.py`); instead, IBKR is configured via `connection_config` in the provider config object, with a dedicated endpoint `PUT /api/admin/providers/ibkr/gateway`. The frontend must reflect this distinction: for IBKR, `IbkrConnectionSection` is rendered (reads/writes `connection_config`), for all others `ApiKeyAuthSection` (reads/writes `PUT /api/admin/credentials/{provider}`).

**Blank field behavior (frontend contract):** The frontend SHALL omit blank credential fields from the `PUT /api/admin/credentials/{provider}` payload. The backend `save()` call does not skip empty values — sending `""` overwrites the stored value with an empty string. Client-side omission is the only protection.

### D7: IBKR Data Source and Scope in the Frontend

`IbkrConnectionSection` renders **all 6 fields** from `CONNECTION_CONFIG_ALLOWLIST["ibkr"]`: `host`, `port`, `client_id`, `account_id`, `env` (dropdown: live/paper), `market_data_type` (dropdown: 1/2/3/4). It reads from `GET /api/admin/providers/ibkr/config` → `connection_config` and writes via `PUT /api/admin/providers/ibkr/gateway` (backend model extended to accept all 6 fields).

The **Connection Config JSON textarea** in the Configuration tab is **suppressed for IBKR** to avoid edit conflicts. All IBKR connection fields are managed exclusively in the Connection / Auth tab.

### D8: Schwab State CSRF — In-Memory Store

The `state` value from `schwab.auth.get_auth_context()` is stored in a module-level `dict[str, tuple[AuthContext, datetime]]` in `routes_admin.py`, keyed by the state string. On each `GET /api/admin/schwab/auth/url` call:
1. Previous pending states older than 10 minutes are evicted
2. New `(auth_context, timestamp)` tuple is inserted

On `GET /api/admin/schwab/callback`:
1. `state` param is looked up in the store
2. If not found or expired: write `callback_error` to transient error store, return HTML error
3. If found: pop the entry, proceed with token exchange

**Transient error store:** A separate module-level `dict[str, tuple[str, datetime]]` keyed by a constant `"schwab_callback_error"`, storing `(error_message, timestamp)`. `GET /api/admin/schwab/auth/status` reads this store and returns `{"status": "callback_error", "error": error_message}` if a recent error (< 5 min) exists. The store is cleared on successful token exchange.

### D9: `?expand=schwab` Auto-Expand is Mandatory

The Dashboard "Re-authorize" button navigates to `/admin/providers?expand=schwab`. `ProvidersPage` reads this URL parameter on mount: if `expand=schwab` is present, it auto-expands the Schwab accordion and switches to the "Connection / Auth" tab. This is not optional — without it, the Dashboard alert flow is a dead-end.

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| Schwab OAuth callback fails (network, code expired) | Fallback: Error state in `SchwabOAuthSection` with "Try again" button; polling timeout after 60s with clear error message |
| `redirect_uri` in Schwab Developer App must be set to `http://localhost:8000/api/admin/schwab/callback` | Documentation info-text in Settings page; backend returns helpful error if redirect_uri is wrong |
| User had webhook URL configured — gone after update | **Breaking Change** for Alert users, but explicitly desired; backend endpoint may remain one version for rollback |
| Accordion with tabs can become deep with many fields | MUI Tabs are scrollable by default; AccordionDetails has max-height with overflow |
| Polling (step 7) may run longer than necessary | Polling stops after 60s with timeout message; user can manually refresh |

## Migration Plan

1. Build new components in parallel with existing ones
2. Backend: add new `GET /api/admin/schwab/callback` endpoint (unauthenticated, state-validated); extend `IbkrGatewayUpdate` to all 6 fields; update `SCHWAB_CALLBACK_URL` default
3. Backend: add transient error store and update `GET /api/admin/schwab/auth/status` to return `callback_error` state
4. Backend: mark `POST /api/admin/schwab/auth/callback` as deprecated (`deprecated=True` on router)
5. Frontend: implement `ProviderDetailsPanel`, `ProviderConfigSection`, `ApiKeyAuthSection`, `IbkrConnectionSection`, `SchwabOAuthSection`
6. Frontend: integrate into `ProvidersPage` with filter chips and `?expand=schwab` support
7. Router: activate new routes, deactivate old ones; Sidebar: 3 entries only

## Open Questions

- ~~Should `SchwabOAuthSection` share the `['schwab-status']` query key?~~ → **Resolved:** use `['schwab', 'status']` (hierarchical, consistent with React Query conventions). All components touching Schwab status must use this exact key.
- ~~Should auto-expand be optional?~~ → **Resolved:** mandatory. `?expand=schwab` auto-expands accordion and switches to Connection / Auth tab.
- ~~Should polling detect backend callback errors?~~ → **Resolved:** yes, via transient error store in backend. Status endpoint returns `{status: "callback_error", error: "..."}`.
- **Open:** Should `IbkrGatewayUpdate` (the backend Pydantic model) be extended in-place to 6 fields, or should a new `IbkrConnectionConfigUpdate` model be used alongside the existing one? → Recommended: extend `IbkrGatewayUpdate` in-place (simpler, no new endpoint needed). The endpoint name `/providers/ibkr/gateway` remains unchanged.
