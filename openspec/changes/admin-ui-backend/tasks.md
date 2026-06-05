## 0. Encrypted SQLite Store (AES-256-GCM)

- [x] 0.1 Add `APP_ENCRYPTION_KEY` and `KEYS_DB_PATH` settings to `app/config.py`; validate `APP_ENCRYPTION_KEY` decodes to exactly 32 bytes at startup — raise `ValueError` and refuse to start if invalid or absent
- [x] 0.2 Update `.env.example` with `APP_ENCRYPTION_KEY` (document key generation command) and `KEYS_DB_PATH=./keys.db`
- [x] 0.3 Add `cryptography` to `pyproject.toml` dependencies and run `uv sync`
- [x] 0.4 Create `app/admin/crypto.py`: `EncryptedBlob` dataclass (`ciphertext`, `iv`, `auth_tag`) and `CryptoService`
- [x] 0.5 Implement `CryptoService.encrypt()`: AES-256-GCM, fresh random 12-byte IV per call, separate auth tag
- [x] 0.6 Implement `CryptoService.decrypt()`: GCM integrity verification, `ValueError` on auth-tag mismatch
- [x] 0.7 Create `app/admin/key_repository.py`: initialize SQLite `keys.db` and create `api_credentials` table with unique `(provider_name, credential_name)`
- [x] 0.8 Implement `KeyRepository.save(provider_name, credential_name, plaintext)` as async via `asyncio.to_thread`: encrypt, upsert, update timestamp
- [x] 0.9 Implement `KeyRepository.get(provider_name, credential_name) -> str | None` as async via `asyncio.to_thread`: load blobs, decrypt, return plaintext
- [x] 0.10 Implement `KeyRepository.list_credentials()`: metadata only (`provider_name`, `credential_name`, `status`, `updated_at`), never plaintext or blobs
- [x] 0.11 Write unit tests for `CryptoService`: round-trip, tampered ciphertext, distinct IV per encrypt call
- [x] 0.12 Write unit tests for `KeyRepository`: save new, update existing, get plaintext, unknown returns `None`, metadata list has no plaintext/blobs

## 1. Provider Runtime Config Store

- [x] 1.1 Create `app/admin/provider_config_repository.py`: initialize `provider_config` table in the same `keys.db`
- [x] 1.2 Table fields: `provider_name PRIMARY KEY`, `enabled`, `timeout_seconds`, `retry_count`, `retry_backoff_seconds`, `rate_limit_per_sec`, `circuit_breaker_enabled`, `circuit_breaker_failure_threshold`, `circuit_breaker_reset_seconds`, `connection_config_json`, `updated_at`
- [x] 1.3 Implement `ProviderConfigRepository.get(provider_name)`: return DB row or defaults from `settings` if no row exists
- [x] 1.4 Implement `ProviderConfigRepository.save(provider_name, config)`: validate values, upsert row, update timestamp
- [x] 1.5 Implement `ProviderConfigRepository.list_all()`: return config for every known provider, merging DB rows with defaults
- [x] 1.6 Add allowlist/defaults for provider-specific `connection_config`: IBKR host/port, Schwab callback/token fallback path, LSEG/Finnhub/Polygon no required connection config
- [x] 1.7 Write unit tests for provider config defaults, upsert, validation, and provider-specific connection config

## 2. Admin Auth

- [x] 2.1 Add remaining settings to `app/config.py`: `ADMIN_AUTH_ENABLED`, `ADMIN_OIDC_ISSUER`, `ADMIN_OIDC_CLIENT_ID`, `ADMIN_OIDC_CLIENT_SECRET`, `SCHWAB_ALERT_WEBHOOK_URL`, `SCHWAB_ALERT_WEBHOOK_FORMAT`
- [x] 2.2 Add `python-jose[cryptography]` to `pyproject.toml` dependencies and run `uv sync`
- [x] 2.3 Create `app/api/admin_auth.py`: `AdminAuth` FastAPI dependency class
- [x] 2.4 Implement `ADMIN_AUTH_ENABLED=false` bypass: return mock principal without token check
- [x] 2.5 Implement JWKS fetch from `{ADMIN_OIDC_ISSUER}/.well-known/jwks.json` with 1-hour in-process cache
- [x] 2.6 Implement JWT validation using `python-jose`; retry with cache refresh on unknown `kid`
- [x] 2.7 Implement `GET /api/admin/auth/url?code_challenge=...`: validate SPA-generated PKCE challenge, return authorization URL with `code_challenge_method=S256`
- [x] 2.8 Implement `POST /api/admin/auth/token`: proxy code + code_verifier to OIDC token endpoint, return access token
- [x] 2.9 Implement `GET /api/admin/auth/me`: return principal info or `{"user": "local", "auth_enabled": false}`
- [x] 2.10 Write unit tests for auth dependency and auth endpoints

## 3. Provider Registry Runtime Reload

- [x] 3.1 Add `reload_from_config()` method to `ProviderRegistry` guarded by `asyncio.Lock`
- [x] 3.2 `reload_from_config()` reads enabled providers and runtime config from `ProviderConfigRepository`
- [x] 3.3 Close providers that become disabled; instantiate providers that become enabled
- [x] 3.4 Apply timeout/retry/rate-limit/circuit-breaker settings to provider instances where supported
- [x] 3.5 Add generic provider runtime config model(s) for timeout, retry, rate limit, and circuit breaker
- [x] 3.6 Write unit tests for registry reload: enable provider, disable provider, config update hot-reloads provider

## 4. Schwab Paused State & Webhook

- [x] 4.1 Add `_paused: bool = False` instance variable to `SchwabProvider.__init__`
- [x] 4.2 Modify `_get_client()`: if `_paused` is `True`, raise `ProviderConnectionError("Schwab provider paused — re-authorization required")` immediately
- [x] 4.3 Modify `_get_client()`: attempt `KeyRepository.get("schwab", "token_json")` first; if present write to temp file and pass to `easy_client()`; fall back to `SCHWAB_TOKEN_PATH` if absent
- [x] 4.4 Modify `_handle_error_status()`: on 401/403 with previously initialized client, set `_paused = True`, clear `_client`, then fire webhook
- [x] 4.5 Implement `_fire_webhook(message: str)`: POST to `SCHWAB_ALERT_WEBHOOK_URL` as fire-and-forget task, log warning on failure
- [x] 4.6 Implement `unpause()` method on `SchwabProvider`: sets `_paused = False`, clears `_client`
- [x] 4.7 Write unit tests for paused state, webhook fire, unpause flow, and KeyRepository token load path

## 5. Admin Routes — Keys & Credentials

- [x] 5.1 Create `app/api/routes_admin.py` with router prefix `/api/admin` and `AdminAuth` dependency applied to all routes
- [x] 5.2 Define credential allowlist per provider: `schwab.api_key`, `schwab.app_secret`, `schwab.token_json`, `schwab.alert_webhook_url`, `finnhub.api_key`, `polygon.api_key`, `lseg.app_key`, `lseg.username`, `lseg.password`
- [x] 5.3 Implement `GET /api/admin/keys`: call `KeyRepository.list_credentials()`, return metadata list only — no plaintext, no blobs
- [x] 5.4 Implement `POST /api/admin/keys`: accept `{"provider_name", "credential_name", "value"}`, validate allowlist, call `KeyRepository.save()`
- [x] 5.5 Implement `GET /api/admin/credentials`: return all allowlisted credential slots with configured/unconfigured state and metadata
- [x] 5.6 Implement `PUT /api/admin/credentials/{provider}`: validate credential names and save each plaintext via `KeyRepository.save(provider, credential_name, value)`
- [x] 5.7 Write unit tests for keys/credentials endpoints: encrypted save, metadata only, unknown provider/credential rejected

## 6. Admin Routes — Providers & Runtime Config

- [x] 6.1 Implement `GET /api/admin/providers`: return all known providers with enabled/status/error and runtime config summary from `ProviderConfigRepository`
- [x] 6.2 Implement `POST /api/admin/providers/{name}/enable`: set `enabled=true` in `ProviderConfigRepository`, call `registry.reload_from_config()`
- [x] 6.3 Implement `POST /api/admin/providers/{name}/disable`: set `enabled=false` in `ProviderConfigRepository`, call `registry.reload_from_config()`
- [x] 6.4 Implement `GET /api/admin/providers/{name}/config`: return full runtime config for provider
- [x] 6.5 Implement `PUT /api/admin/providers/{name}/config`: validate/update timeout, retry, rate limit, circuit breaker, and connection config; call `registry.reload_from_config()`
- [x] 6.6 Implement `PUT /api/admin/providers/ibkr/gateway`: compatibility shortcut that updates `provider_config.connection_config_json` for `ibkr`
- [x] 6.7 Write unit tests for enable/disable, config get/update, validation, IBKR gateway shortcut

## 7. Admin Routes — Schwab Auth

- [x] 7.1 Implement `GET /api/admin/schwab/auth/url`: use Schwab credentials from `KeyRepository` (`schwab.api_key`, `schwab.app_secret`), return `auth_url`; return 503 if missing
- [x] 7.2 Implement `POST /api/admin/schwab/auth/callback`: call `client_from_received_url()` in `asyncio.to_thread()`, save token JSON via `KeyRepository.save("schwab", "token_json", token_json)`, call `SchwabProvider.unpause()`
- [x] 7.3 Implement `GET /api/admin/schwab/auth/status`: check `KeyRepository.get("schwab", "token_json")` primary and `SCHWAB_TOKEN_PATH` fallback, check `_paused`, return status/days_remaining/expires_at
- [x] 7.4 Write unit tests for auth callback: mock schwab-py, verify `KeyRepository.save("schwab", "token_json", ...)`, verify unpause called

## 8. Admin Routes — Alerts

- [x] 8.1 Store `SCHWAB_ALERT_WEBHOOK_URL` as encrypted credential `schwab.alert_webhook_url`; store `SCHWAB_ALERT_WEBHOOK_FORMAT` as non-secret provider config or plain SQLite config
- [x] 8.2 Implement `PUT /api/admin/alerts/webhook`: persist webhook URL and format in SQLite (not K8s Secret / `.env`)
- [x] 8.3 Implement `POST /api/admin/alerts/test`: send test message to configured webhook URL, return `{"status": "sent"}` or error detail

## 9. FastAPI Integration

- [x] 9.1 Initialize `CryptoService`, `KeyRepository`, and `ProviderConfigRepository` singletons at startup in `app/main.py` lifespan
- [x] 9.2 Mount `StaticFiles` in `app/main.py` at `/admin` pointing to `app/static/admin/` — skip gracefully if directory does not exist
- [x] 9.3 Add catch-all route `GET /admin/{full_path:path}` returning `index.html` for client-side routing (only when directory exists)
- [x] 9.4 Include `routes_admin.router` in `app/main.py`
- [x] 9.5 Run `uv run ruff check app/` — zero errors
- [x] 9.6 Run `uv run pytest --maxfail=1 --disable-warnings` — all existing tests pass, all new admin + crypto tests pass

## 10. K8s Manifests & Dockerfile

- [x] 10.1 Add `keys.db` volume mount to `docker-compose.yml` and `k8s/` deployment (PersistentVolumeClaim for SQLite file)
- [x] 10.2 Add `APP_ENCRYPTION_KEY` to K8s Secret and deployment env vars; document key generation and backup requirements
- [x] 10.3 Remove planned K8s Secret patch/RBAC for provider credentials — admin-managed provider data goes to SQLite only
- [x] 10.4 Update K8s deployment manifest: add `ADMIN_AUTH_ENABLED`, `ADMIN_OIDC_ISSUER`, `ADMIN_OIDC_CLIENT_ID`, `ADMIN_OIDC_CLIENT_SECRET` env vars as needed
- [x] 10.5 Add `node:20-alpine` build stage to `Dockerfile` for future frontend build (`COPY admin/ ./admin/ && cd admin && npm ci && npm run build`)
- [x] 10.6 In Python stage: `COPY --from=node-builder /build/admin/dist ./app/static/admin/` (stage present but no-op until frontend change is applied)
- [x] 10.7 Update `.github/agents/schwab.agent.md`: document `_paused`, `unpause()`, webhook behavior, KeyRepository token storage, and ProviderConfigRepository runtime settings
- [x] 10.8 Run `docker build -t market-data-hub:admin-ui-backend .` and verify `GET /health` and existing endpoints still work
