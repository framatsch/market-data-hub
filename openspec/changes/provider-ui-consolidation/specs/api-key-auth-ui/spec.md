## ADDED Requirements

### Requirement: API Key List in Provider Authentication Tab
The `ApiKeyAuthSection` component SHALL render a vertically-stacked list of credential fields for the given provider. This component SHALL be used for finnhub, polygon, lseg, and Schwab. It SHALL NOT be used for IBKR (which uses `IbkrConnectionSection` for host/port). Each credential SHALL have a label (credential name), a password-type input field, and a status chip indicating whether the credential is currently configured.

#### Scenario: Credential status chip
- **WHEN** a credential has been previously saved
- **THEN** the input SHALL show a green "Configured" chip next to the label

#### Scenario: Unconfigured credential
- **WHEN** no value has been stored for a credential
- **THEN** the input SHALL show a grey "Not set" chip

#### Scenario: Save single provider credentials
- **WHEN** the user enters values and clicks "Save Credentials"
- **THEN** the system SHALL call `PUT /api/admin/credentials/{provider}` with all fields (blank fields omitted or passed as empty to preserve existing)
- **THEN** the system SHALL show a success snackbar "Credentials saved"

#### Scenario: Test connection after saving
- **WHEN** the user clicks "Test Connection"
- **THEN** the system SHALL call `POST /api/admin/test-connection/{provider}` and show the result (success/error message + collapsible details) inline within the Authentication tab

### Requirement: API Key Auth Data Source
The `ApiKeyAuthSection` SHALL fetch its credential metadata from `GET /api/admin/credentials` filtered to the current provider, using the shared React Query cache with key `['credentials']`.

#### Scenario: Shared cache
- **WHEN** credentials are saved for one provider
- **THEN** the `['credentials']` cache SHALL be invalidated so all open panels reflect the new state
