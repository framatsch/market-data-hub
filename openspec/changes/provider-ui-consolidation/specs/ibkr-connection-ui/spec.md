## ADDED Requirements

### Requirement: IBKR Gateway Connection Fields in Authentication Tab
The `IbkrConnectionSection` component SHALL render two input fields: Host and Port. This component SHALL be used exclusively for the IBKR provider. It SHALL replace the `ApiKeyAuthSection` for IBKR (IBKR has no API keys stored in CREDENTIAL_ALLOWLIST).

#### Scenario: Host and Port pre-filled
- **WHEN** the Authentication tab opens for IBKR
- **THEN** the Host and Port fields SHALL be pre-filled from `GET /api/admin/providers/ibkr/config` → `connection_config.host` and `connection_config.port`

#### Scenario: Edit host and port
- **WHEN** the user changes the Host or Port value and clicks "Save"
- **THEN** the system SHALL call `PUT /api/admin/providers/ibkr/gateway` with `{"host": "...", "port": ...}`
- **THEN** the system SHALL show a success snackbar "IBKR gateway connection updated"

#### Scenario: Test connection
- **WHEN** the user clicks "Test Connection"
- **THEN** the system SHALL call `POST /api/admin/test-connection/ibkr` and show the result inline

#### Scenario: Default values
- **WHEN** no `connection_config.host` or `connection_config.port` has been set
- **THEN** host SHALL default to "127.0.0.1" and port SHALL default to "4001"

### Requirement: Auth Section Routing by Provider
The `ProvidersPage` SHALL render different contents in the Authentication tab depending on the provider name.

#### Scenario: IBKR shows connection section
- **WHEN** `provider.name === 'ibkr'`
- **THEN** the Authentication tab SHALL render `<IbkrConnectionSection />`

#### Scenario: Schwab shows both API keys and OAuth
- **WHEN** `provider.name === 'schwab'`
- **THEN** the Authentication tab SHALL render both `<ApiKeyAuthSection providerName="schwab" />` and `<SchwabOAuthSection />` stacked vertically

#### Scenario: Other providers show API keys
- **WHEN** `provider.name` is finnhub, polygon, or lseg
- **THEN** the Authentication tab SHALL render `<ApiKeyAuthSection providerName={provider.name} />`
