## Context

Market Data Hub currently supports financial data retrieval from IBKR, LSEG, and Finnhub. To diversify data sources and add a developer-friendly stock price API, we are adding the Prixe Stock API (https://prixe.io). The Prixe API uses Bearer token authentication and accepts `POST` requests for retrieving data, like current stock price, historical data, news, and SEC forms.

## Goals / Non-Goals

**Goals:**
- Implement a new `PrixeProvider` adhering to the `app/providers/base.py` abstract interface.
- Add configuration support for the `PRIXE_API_KEY` in `app/config.py`.
- Map Prixe JSON responses to existing Market Data Hub internal Pydantic models (with `Decimal` for financial values).

**Non-Goals:**
- Removing or replacing any existing providers (e.g., LSEG, IBKR, Finnhub).
- Extending the internal data models; we will only map Prixe data to what is already available.

## Decisions

- **HTTP Client**: Use the existing pinned `httpx==0.26.0` dependency since the Prixe API is HTTP-based and the application is async-first.
- **Provider Architecture**: Create `app/providers/prixe.py` implementing the base provider methods. This isolates Prixe-specific logic from the rest of the application.
- **Authentication**: Bearer tokens will be attached as headers (`Authorization: Bearer <API_KEY>`) to each `httpx` request via a shared `httpx.AsyncClient` session.
- **Error Handling**: Implement custom exception mapping from `httpx.HTTPStatusError` to the internal `AppError` hierarchy in `app/utils/errors.py`.

## Risks / Trade-offs

- **Risk:** Rate limiting on the Prixe API.
  - **Mitigation:** Implement exponential backoff or use existing rate limiting logic in Market Data Hub for HTTP requests.
- **Risk:** Inconsistent JSON structures or missing fields in responses.
  - **Mitigation:** Utilize Pydantic models with robust default values or robust `dict.get` handling with `Decimal` coercion before creating internal objects.
