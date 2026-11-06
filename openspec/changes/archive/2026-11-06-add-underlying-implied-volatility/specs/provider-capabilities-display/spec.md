## MODIFIED Requirements

### Requirement: Provider capabilities displayed in overview
Each provider entry in the Provider Management page SHALL display the service types it supports.

#### Scenario: Capabilities shown as chips in table row
- **WHEN** the provider overview table is displayed
- **THEN** each row SHALL show a "Capabilities" column with chips for each supported service (`Prices`, `Options`, `Companies`, `News`, `Volatility`)

#### Scenario: Capabilities shown as subtitle
- **WHEN** the provider name cell is rendered
- **THEN** a secondary typography line below the name SHALL list capabilities as `Prices · Options · Companies` (dot-separated)

#### Scenario: Backend includes capabilities in response
- **WHEN** `GET /api/admin/providers` is called
- **THEN** each provider object SHALL include `capabilities: string[]`

#### Scenario: LSEG shows volatility capability
- **WHEN** `GET /api/admin/providers` is called and LSEG is listed
- **THEN** its `capabilities` SHALL include `volatility` and the UI SHALL render a `Volatility` chip
