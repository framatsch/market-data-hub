# provider-capabilities-display Specification

## Purpose
Define how the Admin UI Provider Management page shows which service types (prices, options, companies, news, ...) each provider supports.
## Requirements
### Requirement: Provider capabilities displayed in overview
Each provider entry in the Provider Management page SHALL display the service types it supports. Earnings SHALL be shown per interface: `earnings_upcoming` as an `Earnings upcoming` chip and `earnings_history` as an `Earnings history` chip.

#### Scenario: Capabilities shown as chips in table row
- **WHEN** the provider overview table is displayed
- **THEN** each row SHALL show a "Capabilities" column with chips for each supported service (`Prices`, `Options`, `Companies`, `News`, `Volatility`, `Earnings upcoming`, `Earnings history`)

#### Scenario: Capabilities shown as subtitle
- **WHEN** the provider name cell is rendered
- **THEN** a secondary typography line below the name SHALL list capabilities as `Prices · Options · Companies` (dot-separated)

#### Scenario: Backend includes capabilities in response
- **WHEN** `GET /api/admin/providers` is called
- **THEN** each provider object SHALL include `capabilities: string[]`

#### Scenario: LSEG shows volatility capability
- **WHEN** `GET /api/admin/providers` is called and LSEG is listed
- **THEN** its `capabilities` SHALL include `volatility` and the UI SHALL render a `Volatility` chip

#### Scenario: Alpha Vantage shows earnings capabilities
- **WHEN** `GET /api/admin/providers` is called and Alpha Vantage is listed
- **THEN** its `capabilities` SHALL be `["prices", "earnings_upcoming", "earnings_history"]` and the UI SHALL render `Prices`, `Earnings upcoming` and `Earnings history` chips

#### Scenario: Financial Datasets capabilities
- **WHEN** `GET /api/admin/providers` is called and Financial Datasets is listed
- **THEN** its `capabilities` SHALL be `["prices", "companies", "earnings_history"]`

#### Scenario: EarningsAPI capabilities
- **WHEN** `GET /api/admin/providers` is called and EarningsAPI is listed
- **THEN** its `capabilities` SHALL be `["earnings_upcoming", "earnings_history"]`

#### Scenario: IBKR Web API capabilities
- **WHEN** `GET /api/admin/providers` is called and `ibkrweb` is listed
- **THEN** its `capabilities` SHALL be `["prices", "options", "companies", "volatility"]` and the UI SHALL render `Prices`, `Options`, `Companies` and `Volatility` chips, but no `News` chip

