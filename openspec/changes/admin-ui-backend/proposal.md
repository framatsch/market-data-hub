## Why

The Schwab OAuth2 refresh token expires every 7 days and requires a manual browser-based re-authorization via CLI script — a disruptive operational gap that blocks live trading data. More broadly, provider lifecycle management (enabling/disabling, credential rotation, rate-limit/circuit-breaker settings, timeouts, retries, connection settings) has no programmatic interface, forcing direct `.env` edits and restarts. This change delivers the complete FastAPI backend that powers the admin UI: auth, provider management, encrypted SQLite credential storage, provider runtime configuration, and Schwab OAuth2 re-authorization. The frontend is a separate change (`admin-ui-frontend`).

## What Changes

- New `/api/admin/*` REST endpoints for provider management, credential management, Schwab OAuth2 flow, and OIDC auth
- SQLite `keys.db` becomes the runtime configuration store: API keys, OAuth tokens, provider enablement, timeouts, retries, rate limits, and circuit-breaker settings are entered per provider through admin APIs
- `APP_ENCRYPTION_KEY` is the only secret required outside SQLite; in K3s it is supplied via K8s Secret, locally via environment / `.env`
- `SchwabProvider` gains `_paused` state: prevents error-looping on token expiry, fires webhook alert
- Schwab re-authorization via `POST /api/admin/schwab/auth/callback` using `client_from_received_url()` — replaces `schwab-generate-token.py`
- OIDC authentication dependency (`ADMIN_AUTH_ENABLED` toggle, JWKS validation, Authentik-compatible) applied to all admin routes
- Provider enable/disable and runtime-config changes with hot-reload (no restart) via `ProviderRegistry.reload_from_config()`
- FastAPI mounts `app/static/admin/` as StaticFiles at `/admin` (served empty until frontend build exists)
- Dockerfile multi-stage Node build stage added (compiles frontend, copies dist to `app/static/admin/`)

## Capabilities

### New Capabilities

- `admin-auth`: Backend OIDC dependency (`ADMIN_AUTH_ENABLED` toggle, JWKS validation, Authentik-compatible)
- `admin-providers`: Provider status API + enable/disable toggle with registry hot-reload; provider runtime config for rate limit, timeout, retry, circuit breaker, and provider-specific connection fields
- `admin-credentials`: Masked credential read/write for all providers; secrets are encrypted with AES-256-GCM and written to SQLite `keys.db`
- `admin-schwab-auth`: Schwab OAuth2 re-authorization flow (generate URL → user pastes callback URL → token saved → provider unpaused)
- `schwab-paused-state`: `_paused` flag on `SchwabProvider` + `SCHWAB_ALERT_WEBHOOK_URL` webhook on token expiry
- `encrypted-key-store`: AES-256-GCM application-level encryption for all API keys and tokens; SQLite `keys.db` as the storage backend; `CryptoService` + `KeyRepository` replace file-based and env-var credential storage for sensitive secrets

### Modified Capabilities

- `schwab-price-history`: Auth error handling extended — sets `_paused = True` on refresh token expiry; adds webhook alert

## Impact

- **New files**: `app/api/routes_admin.py`, `app/api/admin_auth.py`, `app/admin/crypto.py`, `app/admin/key_repository.py`, `app/admin/provider_config_repository.py`, `app/static/admin/` (gitignored build output)
- **Modified files**: `app/main.py` (StaticFiles mount, admin router), `app/config.py` (new settings), `app/providers/schwab.py` (paused state, KeyRepository integration), `app/providers/registry.py` (reload method), `Dockerfile` (Node build stage, `keys.db` volume mount), `.env.example`
- **New dependencies**: `python-jose[cryptography]`, `cryptography` (AES-GCM via `hazmat`)
- **No breaking changes** to existing API surface
