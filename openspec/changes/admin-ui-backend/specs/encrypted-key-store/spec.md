## ADDED Requirements

### Requirement: APP_ENCRYPTION_KEY validated at startup
The system SHALL read `APP_ENCRYPTION_KEY` from the environment at startup. The key SHALL be base64url-decoded to exactly 32 bytes. If the key is absent, invalid base64, or not exactly 32 bytes after decoding, the application SHALL raise a fatal startup error with a descriptive message and refuse to start.

#### Scenario: Valid 32-byte key accepted
- **WHEN** `APP_ENCRYPTION_KEY` is a valid base64url-encoded 32-byte string
- **THEN** the application starts normally

#### Scenario: Missing key causes startup failure
- **WHEN** `APP_ENCRYPTION_KEY` is not set
- **THEN** the application raises `ValueError: APP_ENCRYPTION_KEY is required` and exits before accepting requests

#### Scenario: Wrong-length key causes startup failure
- **WHEN** `APP_ENCRYPTION_KEY` decodes to fewer or more than 32 bytes
- **THEN** the application raises `ValueError: APP_ENCRYPTION_KEY must decode to exactly 32 bytes (AES-256)` and exits

### Requirement: CryptoService encrypts with AES-256-GCM
`CryptoService` SHALL implement `encrypt(plaintext: str) -> EncryptedBlob` using AES-256-GCM. A fresh random 12-byte IV (nonce) SHALL be generated for each encrypt call. The method SHALL return a dataclass or dict containing `ciphertext: bytes`, `iv: bytes`, and `auth_tag: bytes` as separate fields.

#### Scenario: Encrypt produces distinct IV each call
- **WHEN** `encrypt()` is called twice with the same plaintext
- **THEN** the two returned `iv` values are different (random per call)

#### Scenario: Ciphertext differs from plaintext
- **WHEN** `encrypt("secret-api-key")` is called
- **THEN** `ciphertext` contains no substring of "secret-api-key" in plaintext form

### Requirement: CryptoService decrypts and verifies integrity
`CryptoService.decrypt(ciphertext: bytes, iv: bytes, auth_tag: bytes) -> str` SHALL decrypt the ciphertext using AES-256-GCM and verify the authentication tag. If the tag is invalid (data tampered), the method SHALL raise `ValueError: Decryption failed: authentication tag mismatch`.

#### Scenario: Round-trip encrypt/decrypt returns original plaintext
- **WHEN** a value is encrypted then decrypted with the same key
- **THEN** the decrypted string equals the original plaintext exactly

#### Scenario: Tampered ciphertext raises ValueError
- **WHEN** `decrypt()` is called with a ciphertext that has been modified by one byte
- **THEN** `ValueError` is raised with message indicating authentication failure

### Requirement: SQLite database stores encrypted credentials
The system SHALL create and manage a SQLite database at the path configured by `KEYS_DB_PATH` (default: `./keys.db`). It SHALL contain a table `api_credentials` with columns: `id` (integer primary key), `provider_name` (text, unique), `ciphertext` (blob), `iv` (blob), `auth_tag` (blob), `updated_at` (datetime). The database file SHALL be created automatically on first startup if it does not exist.

#### Scenario: Database created on first run
- **WHEN** `KEYS_DB_PATH` points to a non-existent file at startup
- **THEN** the file is created and `api_credentials` table is initialized

#### Scenario: Schema is idempotent
- **WHEN** the application starts and the database already exists with the correct schema
- **THEN** no error is raised and no data is lost

### Requirement: KeyRepository upserts encrypted credentials
`KeyRepository.save(provider_name: str, plaintext: str)` SHALL encrypt the plaintext via `CryptoService`, then insert or replace the row for `provider_name` in `api_credentials`. On update, the existing row SHALL be fully overwritten (upsert). `updated_at` SHALL be set to the current UTC timestamp.

#### Scenario: New provider saved
- **WHEN** `save("finnhub", "api-key-value")` is called and no row exists for "finnhub"
- **THEN** a new row is inserted with encrypted blobs and current `updated_at`

#### Scenario: Existing provider updated
- **WHEN** `save("schwab", "new-token-json")` is called and a row already exists for "schwab"
- **THEN** the existing row is overwritten (not duplicated) with new ciphertext and `updated_at`

### Requirement: KeyRepository retrieves and decrypts credentials
`KeyRepository.get(provider_name: str) -> str | None` SHALL load the encrypted blobs for the given provider, call `CryptoService.decrypt()`, and return the plaintext string. If no row exists for the provider, return `None`.

#### Scenario: Configured provider returned as plaintext
- **WHEN** a key was previously saved for "schwab" and `get("schwab")` is called
- **THEN** the original plaintext string is returned

#### Scenario: Unconfigured provider returns None
- **WHEN** no row exists for "polygon" and `get("polygon")` is called
- **THEN** `None` is returned without raising an exception

### Requirement: GET /api/admin/keys returns metadata only
`GET /api/admin/keys` SHALL return a list of all rows in `api_credentials`. The response SHALL contain only metadata: `provider_name`, `status` (`"configured"`), and `updated_at`. The endpoint SHALL never include `ciphertext`, `iv`, `auth_tag`, or any decrypted plaintext in the response.

#### Scenario: Configured providers listed
- **WHEN** rows exist for "schwab" and "finnhub" and `GET /api/admin/keys` is called
- **THEN** response is `[{"provider_name": "schwab", "status": "configured", "updated_at": "..."}, {"provider_name": "finnhub", "status": "configured", "updated_at": "..."}]`

#### Scenario: No plaintext in response
- **WHEN** `GET /api/admin/keys` is called
- **THEN** the response body contains no field named `api_key`, `plaintext`, `ciphertext`, or `token`

### Requirement: POST /api/admin/keys stores credential securely
`POST /api/admin/keys` SHALL accept `{"provider_name": str, "api_key": str}`, call `KeyRepository.save()`, and return `{"provider_name": str, "status": "configured", "updated_at": str}`. The endpoint SHALL validate that `provider_name` is a known provider (same allowlist as credential routes). Unknown provider names SHALL return HTTP 400.

#### Scenario: Valid provider key stored
- **WHEN** `POST /api/admin/keys` is called with `{"provider_name": "schwab", "api_key": "token-json-string"}`
- **THEN** the key is encrypted and stored, response is `{"provider_name": "schwab", "status": "configured", "updated_at": "..."}`

#### Scenario: Unknown provider rejected
- **WHEN** `POST /api/admin/keys` is called with `{"provider_name": "unknown_broker", "api_key": "..."}`
- **THEN** HTTP 400 is returned with `{"detail": "Unknown provider: unknown_broker"}`

### Requirement: Schwab token stored in KeyRepository instead of token.json file
`SchwabProvider` SHALL use `KeyRepository` as the primary storage for the Schwab OAuth2 token JSON. When `POST /api/admin/schwab/auth/callback` completes successfully, the token JSON string SHALL be passed to `KeyRepository.save("schwab_token", token_json)` instead of writing to `SCHWAB_TOKEN_PATH`. On `_get_client()`, the provider SHALL first attempt to load the token from `KeyRepository.get("schwab_token")` and write it to a temporary file if needed by `schwab-py`, falling back to `SCHWAB_TOKEN_PATH` if the repository returns `None` (backward compatibility).

#### Scenario: Token saved to KeyRepository on re-auth
- **WHEN** `POST /api/admin/schwab/auth/callback` succeeds
- **THEN** `KeyRepository.save("schwab_token", token_json_str)` is called and no plaintext file is written to disk

#### Scenario: Token loaded from KeyRepository on client init
- **WHEN** `_get_client()` is called and `KeyRepository.get("schwab_token")` returns a value
- **THEN** the token JSON is written to a temp file and `easy_client()` is called with that path

#### Scenario: Backward compatibility with token file
- **WHEN** `KeyRepository.get("schwab_token")` returns `None` and `SCHWAB_TOKEN_PATH` exists
- **THEN** `easy_client()` is called with `SCHWAB_TOKEN_PATH` directly (existing behavior preserved)

### Requirement: KeyRepository uses asyncio-compatible SQLite access
Since the FastAPI application is async, all `KeyRepository` database operations SHALL be executed via `asyncio.to_thread()` to avoid blocking the event loop. The underlying SQLite connection SHALL use `check_same_thread=False`.

#### Scenario: DB operations non-blocking
- **WHEN** `KeyRepository.save()` or `KeyRepository.get()` is called from an async context
- **THEN** the call completes without blocking the event loop (executed in a thread pool)
