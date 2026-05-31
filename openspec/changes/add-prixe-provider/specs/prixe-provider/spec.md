## ADDED Requirements

### Requirement: Prixe configuration
The system SHALL accept `PRIXE_API_KEY` to authenticate requests with the Prixe Stock API.

#### Scenario: Missing API Key
- **WHEN** the `PRIXE_API_KEY` is not provided or empty
- **THEN** the system SHALL disable the Prixe provider or raise a configuration error.

### Requirement: Fetch last sold price
The system SHALL retrieve the last sold price from the Prixe API via `POST /api/last_sold`.

#### Scenario: Successful retrieval
- **WHEN** querying a valid ticker via the Prixe provider
- **THEN** the system SHALL perform a `POST` request with the ticker in the payload, use the Bearer token, and return a parsed data object.

### Requirement: Mapping to internal models
The system SHALL convert price points from the Prixe API response into Market Data Hub's internal models with Decimal types.

#### Scenario: Parsing JSON response
- **WHEN** a valid JSON response is received from Prixe API
- **THEN** the system SHALL extract the required fields, convert financial values to `Decimal`, and return a fully typed Pydantic model.