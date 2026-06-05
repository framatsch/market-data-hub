## 0. Encrypted Key Store (SQLite + AES-256-GCM)

- [ ] 0.1 Add `APP_ENCRYPTION_KEY` and `KEYS_DB_PATH` settings to `app/config.py`; validate `APP_ENCRYPTION_KEY` decodes to exactly 32 bytes at startup — raise `ValueError` and refuse to start if invalid or absent
- [ ] 0.2 Update `.env.example` with `APP_ENCRYPTION_KEY` (document: generate with `python -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"`) and `KEYS_DB_PATH=./keys.db`
- [ ] 0.3 Add `cryptography` to `pyproject.toml` dependencies and run `uv sync`
- [ ] 0.4 Create `app/admin/crypto.py`: `EncryptedBlob` dataclass (`ciphertext: bytes`, `iv: bytes`, `auth_tag: bytes`) and `CryptoService` class initialized with the 32-byte key
- [ ] 0.5 Implement `CryptoService.encrypt(plaintext: str) -> EncryptedBlob`: generate random 12-byte IV per call, encrypt with `AES-256-GCM` via `cryptography.hazmat.primitives.ciphers.aead.AESGCM`, return `EncryptedBlob`
- [ ] 0.6 Implement `CryptoService.decrypt(blob: EncryptedBlob) -> str`: decrypt and verify GCM auth tag; raise `ValueError("Decryption failed: authentication tag mismatch")` on tampered data
- [ ] 0.7 Create `app/admin/key_repository.py`: `KeyRepository` class taking `CryptoService` as dependency; SQLite connection with `check_same_thread=False`; create `api_credentials` table on init (`id`, `provider_name UNIQUE`, `ciphertext`, `iv`, `auth_tag`, `updated_at`)
- [ ] 0.8 Implement `KeyRepository.save(provider_name: str, plaintext: str)` as async (uses `asyncio.to_thread`): encrypt via `CryptoService`, upsert row (`INSERT OR REPLACE`), set `updated_at = UTC now`
- [ ] 0.9 Implement `KeyRepository.get(provider_name: str) -> str | None` as async: load blobs, decrypt via `CryptoService`, return plaintext; return `None` if no row found
- [ ] 0.10 Implement `KeyRepository.list_providers() -> list[dict]` as async: return rows as `[{"provider_name": ..., "status": "configured", "updated_at": ...}]` — no blobs, no plaintext
- [ ] 0.11 Write unit tests for `CryptoService`: round-trip, tampered-ciphertext raises `ValueError`, distinct IV per encrypt call
- [ ] 0.12 Write unit tests for `KeyRepository`: save new, save updates existing, get returns plaintext, get unknown returns `None`, list returns metadata only

## 1. Config & Credential Store

- [ ] 1.1 Add remaining settings to `app/config.py`: `ADMIN_AUTH_ENABLED`, `ADMIN_OIDC_ISSUER`, `ADMIN_OIDC_CLIENT_ID`, `ADMIN_OIDC_CLIENT_SECRET`, `ADMIN_K8S_SECRET_NAME`, `CREDENTIAL_STORE`, `SCHWAB_ALERT_WEBHOOK_URL`
- [ ] 1.2 Update `.env.example` with all new settings and documentation comments (Phase 0 handles `APP_ENCRYPTION_KEY` / `KEYS_DB_PATH`)
- [ ] 1.3 Create `app/admin/credential_store.py`: abstract `CredentialStore` base class with `read(key)` and `write(key, value)` methods; non-secret config (provider enable/disable, IBKR host) uses this; secrets use `KeyRepository`
- [ ] 1.4 Implement `EnvFileCredentialStore` using `python-dotenv` `set_key()` / `dotenv_values()`
- [ ] 1.5 Implement `K8sCredentialStore` using `kubernetes` Python client (`patch_namespaced_secret`)
- [ ] 1.6 Implement auto-detection factory: `KUBERNETES_SERVICE_HOST` present → K8s, otherwise env file; `CREDENTIAL_STORE` env var overrides
- [ ] 1.7 Add `kubernetes` and `python-jose[cryptography]` to `pyproject.toml` dependencies and run `uv sync`

## 2. Admin Auth

- [ ] 2.1 Create `app/api/admin_auth.py`: `AdminAuth` FastAPI dependency class
- [ ] 2.2 Implement `ADMIN_AUTH_ENABLED=false` bypass: return mock principal without any token check
- [ ] 2.3 Implement JWKS fetch from `{ADMIN_OIDC_ISSUER}/.well-known/jwks.json` with 1-hour in-process cache
- [ ] 2.4 Implement JWT validation using `python-jose` against cached JWKS; retry with cache refresh on unknown `kid`
- [ ] 2.5 Implement `GET /api/admin/auth/url`: generate PKCE code verifier/challenge, return authorization URL
- [ ] 2.6 Implement `POST /api/admin/auth/token`: proxy code + code_verifier to OIDC token endpoint, return access token
- [ ] 2.7 Implement `GET /api/admin/auth/me`: return principal info or `{"user": "local", "auth_enabled": false}`
- [ ] 2.8 Write unit tests for auth dependency (mock JWKS, test bypass, test invalid token rejection)

## 3. Schwab Paused State & Webhook

- [ ] 3.1 Add `_paused: bool = False` instance variable to `SchwabProvider.__init__`
- [ ] 3.2 Modify `_get_client()`: if `_paused` is `True`, raise `ProviderConnectionError("Schwab provider paused — re-authorization required")` immediately
- [ ] 3.3 Modify `_get_client()`: attempt `KeyRepository.get("schwab_token")` first; if result is non-None write to temp file and pass to `easy_client()`; fall back to `SCHWAB_TOKEN_PATH` if `None`
- [ ] 3.4 Modify `_handle_error_status()`: on 401/403, check if `_client was not None` at call time; if so, set `_paused = True`, clear `_client`, then fire webhook
- [ ] 3.5 Implement `_fire_webhook(message: str)` async method: POST to `SCHWAB_ALERT_WEBHOOK_URL` as `asyncio.create_task` (fire-and-forget), log warning on failure
- [ ] 3.6 Implement `unpause()` method on `SchwabProvider`: sets `_paused = False`, clears `_client`
- [ ] 3.7 Write unit tests for paused state: test immediate rejection, test webhook fire, test unpause flow, test KeyRepository token load path

## 4. Admin Routes — Keys API

- [ ] 4.1 Implement `GET /api/admin/keys`: call `KeyRepository.list_providers()`, return metadata list — no plaintext, no blobs
- [ ] 4.2 Implement `POST /api/admin/keys`: accept `{"provider_name": str, "api_key": str}`, validate against provider allowlist (400 on unknown), call `KeyRepository.save()`; return `{"provider_name", "status", "updated_at"}`
- [ ] 4.3 Write unit tests for keys endpoints: save stores encrypted, GET never exposes plaintext, unknown provider returns 400

## 5. Admin Routes — Providers & Credentials

- [ ] 5.1 Create `app/api/routes_admin.py` with router prefix `/api/admin` and `AdminAuth` dependency applied to all routes
- [ ] 5.2 Implement `GET /api/admin/providers`: iterate registry, return list with name/enabled/status/error for each known provider
- [ ] 5.3 Add `reload(enabled_providers: list[str])` method to `ProviderRegistry` with asyncio.Lock; closes removed providers, instantiates new ones
- [ ] 5.4 Implement `POST /api/admin/providers/{name}/enable`: add to enabled list, call registry.reload(), persist via CredentialStore
- [ ] 5.5 Implement `POST /api/admin/providers/{name}/disable`: remove from enabled list, call registry.reload(), persist via CredentialStore
- [ ] 5.6 Implement `PUT /api/admin/providers/ibkr/gateway`: accept `{"host": str, "port": int}`, persist IBKR_HOST/IBKR_PORT via CredentialStore (non-secret), reload IBKR provider
- [ ] 5.7 Implement `GET /api/admin/credentials`: return masked metadata for all provider credential keys (delegates to `KeyRepository.list_providers()` for secrets, CredentialStore for non-secrets)
- [ ] 5.8 Implement `PUT /api/admin/credentials/{provider}`: route secret keys (API_KEY, APP_SECRET, tokens) to `KeyRepository.save()`, non-secret keys (HOST, PORT) to CredentialStore
- [ ] 5.9 Define routing split — secret keys per provider: SCHWAB: `API_KEY`, `APP_SECRET`; FINNHUB: `API_KEY`; LSEG: `APP_KEY`, `USERNAME`, `PASSWORD`; IBKR: nothing secret (HOST/PORT → CredentialStore)
- [ ] 5.10 Write unit tests for provider enable/disable and credential write routing (secret → KeyRepository, non-secret → CredentialStore)

## 6. Admin Routes — Schwab Auth

- [ ] 6.1 Implement `GET /api/admin/schwab/auth/url`: call schwab-py auth URL generation, return JSON with `auth_url`; return 503 if credentials not configured
- [ ] 6.2 Implement `POST /api/admin/schwab/auth/callback`: accept `{"received_url": str}`, call `client_from_received_url()` in `asyncio.to_thread()`, call `KeyRepository.save("schwab_token", token_json)`, call `SchwabProvider.unpause()`
- [ ] 6.3 Implement `GET /api/admin/schwab/auth/status`: check `KeyRepository.get("schwab_token")` (primary) and `SCHWAB_TOKEN_PATH` (fallback), check `_paused`, return status/days_remaining/expires_at
- [ ] 6.4 Write unit tests for auth callback: mock schwab-py, verify `KeyRepository.save` called with token JSON, verify unpause called

## 7. Admin Routes — Alerts

- [ ] 7.1 Implement `PUT /api/admin/alerts/webhook`: persist `SCHWAB_ALERT_WEBHOOK_URL` and optional `SCHWAB_ALERT_WEBHOOK_FORMAT` via CredentialStore
- [ ] 7.2 Implement `POST /api/admin/alerts/test`: send test message to configured webhook URL, return `{"status": "sent"}` or error detail

## 8. FastAPI Integration

- [ ] 8.1 Initialize `KeyRepository` singleton at startup in `app/main.py` lifespan (after `APP_ENCRYPTION_KEY` validation)
- [ ] 8.2 Mount `StaticFiles` in `app/main.py` at `/admin` pointing to `app/static/admin/` — skip gracefully if directory does not exist
- [ ] 8.3 Add catch-all route `GET /admin/{full_path:path}` returning `index.html` for client-side routing (only when directory exists)
- [ ] 8.4 Include `routes_admin.router` in `app/main.py`
- [ ] 8.5 Run `uv run ruff check app/` — zero errors
- [ ] 8.6 Run `uv run pytest --maxfail=1 --disable-warnings` — all existing tests pass, all new admin + crypto tests pass

## 9. K8s Manifests & Dockerfile

- [ ] 9.1 Add `keys.db` volume mount to `docker-compose.yml` and `k8s/` deployment (PersistentVolumeClaim for `keys.db`)
- [ ] 9.2 Add `APP_ENCRYPTION_KEY` to K8s Secret and deployment env vars; document key generation command
- [ ] 9.3 Add `Role` and `RoleBinding` to `k8s/` for ServiceAccount to `get`/`patch` the credentials Secret
- [ ] 9.4 Update `k8s/` deployment manifest: add `ADMIN_AUTH_ENABLED`, `ADMIN_OIDC_ISSUER`, `ADMIN_OIDC_CLIENT_ID`, `ADMIN_OIDC_CLIENT_SECRET` env vars sourced from Secret
- [ ] 9.5 Add `node:20-alpine` build stage to `Dockerfile` for future frontend build (`COPY admin/ ./admin/ && cd admin && npm ci && npm run build`)
- [ ] 9.6 In Python stage: `COPY --from=node-builder /build/admin/dist ./app/static/admin/` (stage present but no-op until frontend change is applied)
- [ ] 9.7 Update `.github/agents/schwab.agent.md`: document `_paused` state, `unpause()`, webhook behavior, KeyRepository token storage
- [ ] 9.8 Run `docker build -t market-data-hub:admin-ui-backend .` and verify `GET /health` and existing endpoints still work
