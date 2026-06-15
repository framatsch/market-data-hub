## ADDED Requirements

### Requirement: NewsService wrapper
The backend SHALL provide an `app/services/news_service.py` that exposes a `NewsService` class matching the interface of `BaseNewsProvider`.

#### Scenario: Service queries the registry
- **WHEN** `news_service.get_company_news("AAPL", provider_name="finnhub")` is called
- **THEN** the service asks the `ProviderRegistry` for the specified provider (or the default if None) and delegates the call.

### Requirement: Dependency Injection for NewsService
FastAPI routes that require news data SHALL depend on `NewsServiceDep` instead of injecting `NewsProviderDep` directly.

#### Scenario: Fetching company news via the service
- **WHEN** a client calls `GET /companies/AAPL/news`
- **THEN** the router uses `NewsService` to handle the data fetch.
