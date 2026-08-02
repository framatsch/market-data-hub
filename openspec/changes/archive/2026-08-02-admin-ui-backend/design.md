## Context

MDH is a FastAPI service running in a single container (K3s or local Docker). There is currently no admin API, no authentication layer, and no runtime configuration interface. Provider credentials live in `.env` / K8s Secrets and require a restart to change. The Schwab provider requires manual re-authorization every 7 days via a CLI script (`schwab-generate-token.py`).

This change delivers exclusively the backend. The React frontend is implemented separately in `admin-ui-frontend` and consumes the endpoints defined here. FastAPI will serve the compiled frontend via StaticFiles once the frontend build exists — the mount is added here but the static directory will be empty until the frontend change is applied.

Runtime credentials and provider configuration will be stored in a local SQLite database (`keys.db`) mounted as a Docker/K8s volume. Sensitive values are encrypted at application level before database writes. The only external secret is `APP_ENCRYPTION_KEY`, supplied via K8s Secret in K3s or environment / `.env` locally.

## Goals / Non-Goals

**Goals:**
- All `/api/admin/*` REST endpoints fully functional and tested
- OIDC auth via Authentik for K3s; fully bypassed when `ADMIN_AUTH_ENABLED=false`
- Credential read (masked) and write via encrypted SQLite `KeyRepository`
- Provider runtime configuration stored in SQLite: enabled state, rate limit, timeout, retry policy, circuit-breaker thresholds, and provider-specific connection settings
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

### D3: Credential and provider config storage — SQLite only
`keys.db` is the source of truth for runtime-managed provider data. It contains two repository-backed domains:
- `api_credentials`: encrypted provider credentials and token JSON (`provider_name`, `credential_name`, `ciphertext`, `iv`, `auth_tag`, `updated_at`)
- `provider_config`: non-secret provider runtime settings (`provider_name`, `enabled`, `timeout_seconds`, `retry_count`, `retry_backoff_seconds`, `rate_limit_per_sec`, `circuit_breaker_enabled`, `circuit_breaker_failure_threshold`, `circuit_breaker_reset_seconds`, `connection_config_json`, `updated_at`)

K8s Secrets are no longer used for provider keys, provider enablement, IBKR host/port, Schwab token JSON, or webhook URLs. K8s Secrets only supply `APP_ENCRYPTION_KEY` and optionally OIDC client values.

This simplifies the deployment model: the admin UI writes to SQLite regardless of environment, and K3s only needs a PersistentVolumeClaim for `keys.db` plus one Secret for the encryption key.

### D4: Registry hot-reload via `ProviderRegistry.reload_from_config()`
Add `reload_from_config()` method to `ProviderRegistry`: (1) reads enabled providers and runtime settings from `ProviderConfigRepository`, (2) calls `close()` on providers being removed, (3) instantiates new providers being added, (4) applies timeout/retry/rate-limit/circuit-breaker settings to provider instances where supported. Guarded by asyncio.Lock. In-flight requests complete against old instance (Python object reference semantics).

### D5: Schwab `_paused` state + webhook alert
`_paused: bool` on `SchwabProvider`. When `True`, `_get_client()` raises `ProviderConnectionError` immediately. On 401/403 with non-None client (refresh expiry): set `_paused = True`, fire background webhook via `asyncio.create_task` (fire-and-forget). `unpause()` method sets `_paused = False`, clears `_client`. Called by `POST /api/admin/schwab/auth/callback` on success.

### D6: `client_from_received_url()` wrapped in `asyncio.to_thread()`
schwab-py's token exchange is synchronous. Consistent with existing `easy_client()` pattern in the provider.

## Risks / Trade-offs

- **APP_ENCRYPTION_KEY loss makes DB undecryptable** → losing or rotating the key without migration makes existing credentials unreadable. Mitigation: document backup and key-rotation procedure before production use.
- **SQLite volume loss loses runtime config** → losing `keys.db` loses credentials and provider settings. Mitigation: mount `keys.db` on persistent storage and back it up with cluster backups.
- **JWKS cache stale after key rotation** → up to 1-hour stale. Mitigation: retry with cache refresh on unknown `kid`.
- **Hot-reload race** → request arrives between old provider close and new provider ready. Mitigation: registry lock + close-before-instantiate; worst case one 503.
- **`app/static/admin/` absent in dev** → StaticFiles mount skipped gracefully; `/admin` returns 404 until frontend build exists.

## Migration Plan

1. Deploy updated container — existing API surface unchanged
2. Set `ADMIN_AUTH_ENABLED=false` in `.env` initially, verify admin endpoints work
3. Configure Authentik, set OIDC settings, set `ADMIN_AUTH_ENABLED=true`
4. Add `keys.db` PVC/volume mount and `APP_ENCRYPTION_KEY` K8s Secret
5. Enter provider credentials and provider runtime config through `/api/admin/keys` and provider config endpoints
6. Verify Schwab re-auth flow end-to-end via curl before frontend is deployed

**Rollback:** Remove admin router + StaticFiles mount from `main.py`. Zero impact on existing routes.

## Open Questions

- **Authentik PKCE vs client_secret_post**: Does the Authentik installation support PKCE for public clients? Recommend PKCE — no secret in browser bundle.
- **Alert webhook format**: Slack-compatible `{"text": "..."}` or generic JSON? Add `SCHWAB_ALERT_WEBHOOK_FORMAT=slack|generic` config key.
