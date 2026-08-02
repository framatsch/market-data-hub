# admin-credentials Specification

## Purpose
TBD - created by archiving change admin-ui-backend. Update Purpose after archive.
## Requirements
### Requirement: List credentials with masked metadata only
`GET /api/admin/credentials` SHALL return all known credential slots for all providers. Secret values SHALL never be decrypted for the response. The response SHALL indicate whether each credential is configured and SHALL include `updated_at` metadata when available.

#### Scenario: Configured credential listed without value
- **WHEN** `GET /api/admin/credentials` is called and `finnhub.api_key` exists in SQLite
- **THEN** response includes `{"provider": "finnhub", "credential_name": "api_key", "set": true, "masked_value": "configured", "updated_at": "..."}`

#### Scenario: Unset credential shown
- **WHEN** no row exists for `schwab.app_secret`
- **THEN** response includes `{"provider": "schwab", "credential_name": "app_secret", "set": false, "masked_value": null, "updated_at": null}`

#### Scenario: Plaintext never returned
- **WHEN** `GET /api/admin/credentials` is called
- **THEN** the response body contains no decrypted credential value, no ciphertext, no IV, and no auth tag

### Requirement: Update credentials for a provider in encrypted SQLite
`PUT /api/admin/credentials/{provider}` SHALL accept a JSON object with credential-name to plaintext-value pairs for the specified provider, validate that each credential name is known for that provider, and persist secrets via `KeyRepository.save(provider, credential_name, plaintext)` into encrypted SQLite `keys.db`.

#### Scenario: Successfully update API key
- **WHEN** `PUT /api/admin/credentials/finnhub` is called with `{"api_key": "new-key-value"}`
- **THEN** `KeyRepository.save("finnhub", "api_key", "new-key-value")` is called and response is `{"updated": ["api_key"], "errors": []}`

#### Scenario: Unknown credential rejected
- **WHEN** `PUT /api/admin/credentials/finnhub` is called with `{"unknown_key": "value"}`
- **THEN** response is HTTP 400 with `{"detail": "Unknown credential: unknown_key for provider finnhub"}`

#### Scenario: Credential written to SQLite in K3s
- **WHEN** running in a K8s Pod and `PUT /api/admin/credentials/schwab` is called
- **THEN** the encrypted credential is written to `keys.db` and no K8s Secret is patched

#### Scenario: Credential written to SQLite locally
- **WHEN** running locally and credential is updated
- **THEN** the encrypted credential is written to `keys.db` and `.env` is not modified

### Requirement: Only APP_ENCRYPTION_KEY remains external secret
Provider credentials, provider enablement, provider runtime configuration, webhook URLs, and Schwab token JSON SHALL be stored in SQLite. The only external secret needed for credential protection SHALL be `APP_ENCRYPTION_KEY`, supplied via environment variable / `.env` locally or K8s Secret in K3s.

#### Scenario: Provider key does not require K8s Secret
- **WHEN** Schwab API credentials are entered through admin APIs in K3s
- **THEN** only `keys.db` is updated and no K8s Secret update occurs

#### Scenario: Encryption key remains external
- **WHEN** the app starts in K3s
- **THEN** `APP_ENCRYPTION_KEY` is read from environment supplied by K8s Secret and is never stored in `keys.db`

### Requirement: Credential allowlist per provider
The system SHALL maintain an allowlist of credential names per provider. At minimum it SHALL support: `schwab.api_key`, `schwab.app_secret`, `schwab.token_json`, `schwab.alert_webhook_url`, `finnhub.api_key`, `polygon.api_key`, `lseg.app_key`, `lseg.username`, `lseg.password`.

#### Scenario: Known Schwab credentials accepted
- **WHEN** `PUT /api/admin/credentials/schwab` is called with `{"api_key": "...", "app_secret": "..."}`
- **THEN** both credentials are accepted and saved encrypted

#### Scenario: Polygon credential accepted
- **WHEN** `PUT /api/admin/credentials/polygon` is called with `{"api_key": "..."}`
- **THEN** the credential is accepted and saved encrypted

