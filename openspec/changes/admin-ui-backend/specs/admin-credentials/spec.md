## ADDED Requirements

### Requirement: List credentials with masked values
`GET /api/admin/credentials` SHALL return all known credential keys for all providers. Secret values SHALL be masked (show only last 4 chars or `***` if shorter). The response SHALL indicate whether each key is currently set.

#### Scenario: Credentials listed with masking
- **WHEN** `GET /api/admin/credentials` is called and `FINNHUB_API_KEY=sk-abc123xyz`
- **THEN** response includes `{"key": "FINNHUB_API_KEY", "provider": "finnhub", "set": true, "masked_value": "***xyz"}`

#### Scenario: Unset credential shown
- **WHEN** a credential key is empty or not set
- **THEN** response includes `{"key": "SCHWAB_APP_SECRET", "provider": "schwab", "set": false, "masked_value": null}`

### Requirement: Update credentials for a provider
`PUT /api/admin/credentials/{provider}` SHALL accept a JSON object with credential key-value pairs for the specified provider, validate that the keys are known for that provider, and persist them via CredentialStore.

#### Scenario: Successfully update API key
- **WHEN** `PUT /api/admin/credentials/finnhub` is called with `{"FINNHUB_API_KEY": "new-key-value"}`
- **THEN** CredentialStore writes the value, response is `{"updated": ["FINNHUB_API_KEY"], "errors": []}`

#### Scenario: Unknown key rejected
- **WHEN** `PUT /api/admin/credentials/finnhub` is called with `{"UNKNOWN_KEY": "value"}`
- **THEN** response is HTTP 400 with `{"detail": "Unknown credential key: UNKNOWN_KEY for provider finnhub"}`

#### Scenario: Credential written to K8s Secret in-cluster
- **WHEN** running in a K8s Pod and `PUT /api/admin/credentials/schwab` is called
- **THEN** the K8s Secret named `ADMIN_K8S_SECRET_NAME` is patched with the new value

#### Scenario: Credential written to .env file locally
- **WHEN** `KUBERNETES_SERVICE_HOST` is not set and credential is updated
- **THEN** `python-dotenv` `set_key()` writes the value to `.env`

### Requirement: CredentialStore auto-detection
The system SHALL use a `CredentialStore` abstraction that automatically selects `K8sCredentialStore` when `KUBERNETES_SERVICE_HOST` env var is present, and `EnvFileCredentialStore` otherwise. The active backend SHALL be overridable via `CREDENTIAL_STORE=k8s|env`.

#### Scenario: In-cluster auto-detection
- **WHEN** `KUBERNETES_SERVICE_HOST` is set
- **THEN** `K8sCredentialStore` is used without explicit configuration

#### Scenario: Local auto-detection
- **WHEN** `KUBERNETES_SERVICE_HOST` is not set
- **THEN** `EnvFileCredentialStore` is used without explicit configuration

#### Scenario: Explicit override
- **WHEN** `CREDENTIAL_STORE=env` is set even with `KUBERNETES_SERVICE_HOST` present
- **THEN** `EnvFileCredentialStore` is used
