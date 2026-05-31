# OpenSpec: Prixe Stock API Provider

## Status
- **Type**: Feature
- **Status**: Implemented
- **Date**: 2026-05-31

## Context & Problem
Provide access to real-time and historical stock price data via the Prixe Stock API as an alternative to existing providers (IBKR, LSEG, Polygon).

## Requirements

### 1. Configuration
The system SHALL accept `PRIXE_API_KEY` to authenticate requests with the Prixe Stock API.

#### Scenario: Missing API Key
- **WHEN** the `PRIXE_API_KEY` is not provided or empty
- **THEN** the system SHALL disable the Prixe provider or raise a configuration error.

### 2. Fetch last sold price
The system SHALL retrieve the last sold price from the Prixe API via `POST /api/last_sold`.

#### Scenario: Successful retrieval
- **WHEN** querying a valid ticker via the Prixe provider
- **THEN** the system SHALL perform a `POST` request with the ticker in the payload, use the Bearer token, and return a parsed data object.

### 3. Mapping to internal models
The system SHALL convert price points from the Prixe API response into Market Data Hub's internal models with Decimal types.

#### Scenario: Parsing JSON response
- **WHEN** a valid JSON response is received from Prixe API
- **THEN** the system SHALL extract the required fields, convert financial values to `Decimal`, and return a fully typed Pydantic model.

## Technical Design

### Configuration
```python
# app/config.py
PRIXE_API_KEY: str = ""
```

### Provider Class
The `PrixeProvider` extends `BasePriceProvider` and uses `httpx.AsyncClient` with Bearer token auth to make requests to `POST /api/last_sold`.

HTTP errors are mapped to the internal `AppError` hierarchy.

## Verification Plan
1. Unit test: successful last_sold call returns mapped Pydantic model
2. Unit test: 404 response maps to `DataNotFoundError`
3. Unit test: missing `PRIXE_API_KEY` raises `ProviderNotAvailableError`
4. Unit test: historical prices map correctly for supported intervals
5. Lint: `ruff check app/` passes
6. Tests: `uv run pytest tests/unit/` passes
