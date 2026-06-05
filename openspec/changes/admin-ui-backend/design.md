## Context

MDH is a FastAPI service running in a single container (K3s or local Docker). There is currently no admin API, no authentication layer, and no runtime configuration interface. Provider credentials live in `.env` / K8s Secrets and require a restart to change. The Schwab provider requires manual re-authorization every 7 days via a CLI script (`schwab-generate-token.py`).

This change delivers exclusively the backend. The React frontend is implemented separately in `admin-ui-frontend` and consumes the endpoints defined here. FastAPI will serve the compiled frontend via StaticFiles once the frontend build exists — the mount is added here but the static directory will be empty until the frontend change is applied.

Credential storage differs by environment: K8s Secrets when running in-cluster, `.env` file otherwise. The backend must detect which mode it is in and use the appropriate backend.

## Goals / Non-Goals

**Goals:**
- All `/api/admin/*` REST endpoints fully functional and tested
- OIDC auth via Authentik for K3s; fully bypassed when `ADMIN_AUTH_ENABLED=false`
- Credential read (masked) and write via `CredentialStore` abstraction (K8s / `.env`)
- Schwab OAuth2 re-authorization without CLI tooling
- Runtime provider enable/disable with hot-reload (no restart)
- `_paused` state in `SchwabProvider` to prevent error-looping after token expiry
- Webhook alert when Schwab token expires
- StaticFiles mount at `/admin` (directory may be empty until frontend build)
- Dockerfile multi-stage Node build stage

**Non-Goals:**
- React frontend (separate change: `admin-ui-frontend`)
- Multi-user RBAC
- Audit logging of config changes
- Provider-level alerting beyond Schwab token expiry

## Decisions

### D1: SPA served by FastAPI StaticFiles
FastAPI mounts `app/static/admin/` as StaticFiles at `/admin`. A catch-all route returns `index.html` for client-side routing. Mount is skipped gracefully if directory does not exist (development without frontend build).

### D2: OIDC validation via `python-jose` + JWKS endpoint
`admin_auth.py` fetches JWKS from `{ADMIN_OIDC_ISSUER}/.well-known/jwks.json`, cached in-process, refreshed hourly. JWT Bearer tokens validated against this keyset. On unknown `kid`, one immediate cache refresh before returning 401. Stateless — no session cookies.

**Auth flow (backend side):**
1. `GET /api/admin/auth/url` → generate PKCE code_verifier/challenge, return authorization URL
2. `POST /api/admin/auth/token` → proxy code + code_verifier to OIDC token endpoint, return access token
3. All `/api/admin/*` routes protected by `AdminAuth` dependency (bypassed when `ADMIN_AUTH_ENABLED=false`)

### D3: Credential storage — K8s Secret or `.env`, auto-detected
`CredentialStore` abstraction with two implementations:
- `K8sCredentialStore`: patches K8s Secret `ADMIN_K8S_SECRET_NAME` (default: `market-data-hub-secrets`) via `kubernetes` Python client
- `EnvFileCredentialStore`: uses `python-dotenv` `set_key()` on project root `.env`

Auto-detection: `KUBERNETES_SERVICE_HOST` present → K8s mode. Override via `CREDENTIAL_STORE=env|k8s`.

### D4: Registry hot-reload via `ProviderRegistry.reload(enabled)`
Add `reload(enabled_providers: list[str])` method to `ProviderRegistry`: (1) calls `close()` on providers being removed, (2) instantiates new providers being added, (3) updates `ENABLED_PROVIDERS` via CredentialStore. Guarded by asyncio.Lock. In-flight requests complete against old instance (Python object reference semantics).

### D5: Schwab `_paused` state + webhook alert
`_paused: bool` on `SchwabProvider`. When `True`, `_get_client()` raises `ProviderConnectionError` immediately. On 401/403 with non-None client (refresh expiry): set `_paused = True`, fire background webhook via `asyncio.create_task` (fire-and-forget). `unpause()` method sets `_paused = False`, clears `_client`. Called by `POST /api/admin/schwab/auth/callback` on success.

### D6: `client_from_received_url()` wrapped in `asyncio.to_thread()`
schwab-py's token exchange is synchronous. Consistent with existing `easy_client()` pattern in the provider.

## Risks / Trade-offs

- **K8s Secret patch requires RBAC** → missing Role/RoleBinding causes silent 403. Mitigation: add Role + RoleBinding to `k8s/` manifests.
- **JWKS cache stale after key rotation** → up to 1-hour stale. Mitigation: retry with cache refresh on unknown `kid`.
- **Hot-reload race** → request arrives between old provider close and new provider ready. Mitigation: registry lock + close-before-instantiate; worst case one 503.
- **`app/static/admin/` absent in dev** → StaticFiles mount skipped gracefully; `/admin` returns 404 until frontend build exists.

## Migration Plan

1. Deploy updated container — existing API surface unchanged
2. Set `ADMIN_AUTH_ENABLED=false` in `.env` initially, verify admin endpoints work
3. Configure Authentik, set OIDC settings, set `ADMIN_AUTH_ENABLED=true`
4. Add K8s Role + RoleBinding (K3s deployments)
5. Verify Schwab re-auth flow end-to-end via curl before frontend is deployed

**Rollback:** Remove admin router + StaticFiles mount from `main.py`. Zero impact on existing routes.

## Open Questions

- **Authentik PKCE vs client_secret_post**: Does the Authentik installation support PKCE for public clients? Recommend PKCE — no secret in browser bundle.
- **K8s Secret name**: Is `market-data-hub-secrets` the existing Secret name?
- **Alert webhook format**: Slack-compatible `{"text": "..."}` or generic JSON? Add `SCHWAB_ALERT_WEBHOOK_FORMAT=slack|generic` config key.
