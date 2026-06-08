## ADDED Requirements

### Requirement: 503 when no provider configured
When no default provider of a given type is configured, API endpoints SHALL return HTTP 503 with a descriptive error message.

#### Scenario: Price provider not configured
- **WHEN** `GET /api/prices/{symbol}` is called with no default price provider configured
- **THEN** the response SHALL be HTTP 503 with `detail: "No price provider configured — enable a provider in the admin UI"`

#### Scenario: Options provider not configured
- **WHEN** `GET /api/options/{symbol}/chain` is called with no default options provider configured
- **THEN** the response SHALL be HTTP 503 with `detail: "No options provider configured — enable a provider in the admin UI"`

#### Scenario: News provider not configured
- **WHEN** `GET /api/news/{symbol}` is called with no default news provider configured
- **THEN** the response SHALL be HTTP 503 with `detail: "No news provider configured — enable a provider in the admin UI"`
