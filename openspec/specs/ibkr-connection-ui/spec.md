## ADDED Requirements

### Requirement: IBKR Connection Section Covers All 6 Fields
The `IbkrConnectionSection` component SHALL render form inputs for **all 6 fields** from `CONNECTION_CONFIG_ALLOWLIST["ibkr"]`: `host` (text), `port` (number), `client_id` (number), `account_id` (text), `env` (select: `live` | `paper`), `market_data_type` (select: `1=Live` | `2=Frozen` | `3=Delayed` | `4=Delayed Frozen`). This component is used exclusively for the IBKR provider. IBKR has no API keys in `CREDENTIAL_ALLOWLIST`.

#### Scenario: All fields pre-filled from config
- **WHEN** the Connection / Auth tab opens for IBKR
- **THEN** all 6 fields SHALL be pre-filled from `GET /api/admin/providers/ibkr/config` → `connection_config`

#### Scenario: Default values when not yet customized
- **WHEN** no custom `connection_config` has been saved for IBKR
- **THEN** fields SHALL show defaults: `host=127.0.0.1`, `port=4001`, `client_id=815`, `account_id=DU123456`, `env=paper`, `market_data_type=3`

#### Scenario: Save all 6 fields
- **WHEN** the user edits any field and clicks "Save"
- **THEN** the system SHALL call `PUT /api/admin/providers/ibkr/gateway` with all 6 fields: `{"host": "...", "port": ..., "client_id": ..., "account_id": "...", "env": "...", "market_data_type": ...}`
- **THEN** show a success snackbar "IBKR gateway connection updated"

#### Scenario: Test connection
- **WHEN** the user clicks "Test Connection"
- **THEN** the system SHALL call `POST /api/admin/test-connection/ibkr` and show the result inline

### Requirement: Backend IbkrGatewayUpdate Extended to 6 Fields
The backend Pydantic model `IbkrGatewayUpdate` SHALL be extended to accept all 6 IBKR connection config fields: `host`, `port`, `client_id`, `account_id`, `env`, `market_data_type`. The `PUT /api/admin/providers/ibkr/gateway` endpoint SHALL update `connection_config` with all provided fields (partial updates allowed: fields not present in the payload are left unchanged).

#### Scenario: Partial update preserves unspecified fields
- **WHEN** `PUT /api/admin/providers/ibkr/gateway` is called with only `{"host": "192.168.1.5", "port": 4001}`
- **THEN** `client_id`, `account_id`, `env`, `market_data_type` in `connection_config` SHALL remain unchanged

### Requirement: Connection Config JSON Textarea Suppressed for IBKR
The Connection Config JSON textarea in the Configuration tab SHALL be hidden when `provider.name === 'ibkr'`. All IBKR connection fields are managed exclusively via `IbkrConnectionSection` in the Connection / Auth tab. This prevents conflicting edits between the two UIs.

#### Scenario: JSON textarea hidden for IBKR
- **WHEN** the Configuration tab is shown for IBKR
- **THEN** the Connection Config JSON textarea SHALL NOT be rendered

#### Scenario: JSON textarea visible for other providers
- **WHEN** the Configuration tab is shown for finnhub, polygon, lseg, schwab, mock, or prixe
- **THEN** the Connection Config JSON textarea SHALL be rendered as normal

### Requirement: Auth Section Routing by Provider
The `ProvidersPage` SHALL render different contents in the Connection / Auth tab depending on the provider name.

#### Scenario: IBKR shows connection section
- **WHEN** `provider.name === 'ibkr'`
- **THEN** the Connection / Auth tab SHALL render `<IbkrConnectionSection />`

#### Scenario: Schwab shows both API keys and OAuth
- **WHEN** `provider.name === 'schwab'`
- **THEN** the Connection / Auth tab SHALL render both `<ApiKeyAuthSection providerName="schwab" visibleCredentials={["api_key", "app_secret"]} />` and `<SchwabOAuthSection />` stacked vertically

#### Scenario: Other providers show API keys
- **WHEN** `provider.name` is finnhub, polygon, or lseg
- **THEN** the Connection / Auth tab SHALL render `<ApiKeyAuthSection providerName={provider.name} />`
