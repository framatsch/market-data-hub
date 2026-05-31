## 1. Configuration and Base Setup

- [x] 1.1 Add `PRIXE_API_KEY` to `app/config.py` environment settings.
- [x] 1.2 Create `app/providers/prixe.py` file with basic class skeleton extending the base provider.

## 2. API Integration

- [x] 2.1 Implement HTTP async requests using `httpx.AsyncClient` with the Bearer token authorization header.
- [x] 2.2 Implement the `POST /api/last_sold` endpoint integration in `PrixeProvider`.
- [x] 2.3 Map the Prixe API response fields into Market Data Hub's internal Pydantic models (converting prices to `Decimal`).
- [x] 2.4 Add exception mapping for HTTP errors to the internal `AppError` hierarchy in `app/utils/errors.py`.

## 3. Testing and Validation

- [x] 3.1 Write unit tests for `PrixeProvider` using `pytest` and mocked HTTP responses.
- [x] 3.2 Implement logic to disable or error on missing `PRIXE_API_KEY` during initialization.
- [x] 3.3 Run linter (`ruff check app/`) and test suite (`uv run pytest`) to verify integration.
