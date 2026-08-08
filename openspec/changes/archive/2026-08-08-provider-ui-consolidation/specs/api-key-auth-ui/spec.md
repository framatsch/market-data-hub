## ADDED Requirements

### Requirement: API Key List in Provider Connection / Auth Tab
The `ApiKeyAuthSection` component SHALL render a vertically-stacked list of credential fields for the given provider. This component SHALL be used for finnhub, polygon, lseg, and Schwab. It SHALL NOT be used for IBKR (which uses `IbkrConnectionSection`).

The component accepts an optional `visibleCredentials?: string[]` prop. When provided, only the named credentials are shown. When omitted, all credentials from `GET /api/admin/credentials` for that provider are shown. For Schwab, the caller MUST pass `visibleCredentials={["api_key", "app_secret"]}` to suppress `token_json` (managed by OAuth flow) and `alert_webhook_url` (removed).

Each credential SHALL have a label (credential name), a password-type input field, and a status chip indicating whether the credential is currently configured.

#### Scenario: Credential status chip
- **WHEN** a credential has been previously saved
- **THEN** the input SHALL show a green "Configured" chip next to the label

#### Scenario: Unconfigured credential
- **WHEN** no value has been stored for a credential
- **THEN** the input SHALL show a grey "Not set" chip

#### Scenario: Schwab shows only api_key and app_secret
- **WHEN** `ApiKeyAuthSection` is rendered for Schwab with `visibleCredentials={["api_key", "app_secret"]}`
- **THEN** only `api_key` and `app_secret` fields SHALL be shown
- **THEN** `token_json` and `alert_webhook_url` SHALL NOT be rendered

#### Scenario: Save credentials — blank fields are omitted
- **WHEN** the user enters values and clicks "Save Credentials"
- **THEN** the frontend SHALL build a payload containing ONLY non-blank fields
- **THEN** the system SHALL call `PUT /api/admin/credentials/{provider}` with the filtered payload
- **THEN** the system SHALL show a success snackbar "Credentials saved"

#### Scenario: Blank input preserves existing key
- **WHEN** the user leaves a credential input blank and saves
- **THEN** that field SHALL be omitted from the payload (not sent as empty string)
- **THEN** the existing stored value SHALL be unchanged

#### Scenario: Test connection
- **WHEN** the user clicks "Test Connection"
- **THEN** the system SHALL call `POST /api/admin/test-connection/{provider}` and show the result (success/error message + collapsible details) inline within the Connection / Auth tab

### Requirement: API Key Auth Data Source
The `ApiKeyAuthSection` SHALL fetch its credential metadata from `GET /api/admin/credentials` filtered to the current provider, using the shared React Query cache with key `['credentials']`.

#### Scenario: Shared cache invalidation
- **WHEN** credentials are saved for one provider
- **THEN** the `['credentials']` cache SHALL be invalidated so all open panels reflect the new state
