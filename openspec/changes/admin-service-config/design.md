## Context

Market Data Hub supports multiple providers for pricing, options, company fundamentals, and news. Currently:
- The default provider for each type is loaded from environment variables (`DEFAULT_PRICE_PROVIDER`, `DEFAULT_COMPANY_PROVIDER`, `DEFAULT_OPTIONS_PROVIDER`, `DEFAULT_NEWS_PROVIDER`) at startup.
- Changing a default provider requires restarting the FastAPI service.
- The `NewsService` wrapper is missing. Other domains (prices, companies, options) have a dedicated service class (e.g., `PriceService`), but news endpoints interact directly with `NewsProviderDep`.
- The Admin UI currently manages provider-specific configuration but has no interface for global system defaults.

## Goals / Non-Goals

**Goals:**
- Provide a `NewsService` that wraps `BaseNewsProvider` and handles default provider resolution, consistent with other service classes.
- Store system defaults (like the default provider for each domain) in the SQLite database alongside provider configurations and credentials.
- Expose an API (`/api/admin/settings`) to read and update these global defaults.
- Allow the `ProviderRegistry` to load these defaults during its config reload process without restarting the server.
- Expose a UI in the Admin frontend to select default providers dynamically based on which enabled providers support the relevant base classes.
- Completely remove the legacy environment variables (`DEFAULT_PRICE_PROVIDER`, etc.) and related code, making the database the sole source of truth (with hardcoded fallbacks like 'ibkr' or 'finnhub' if the DB is empty).

**Non-Goals:**
- Modifying the existing logic of `PriceService`, `CompanyService`, or `OptionsService` beyond ensuring they rely on the `ProviderRegistry`'s updated default mechanism.

## Decisions

### D1: `NewsService` Architecture
We will create `app/services/news_service.py` exposing `get_company_news(symbol, ... provider_name=None)`. It will ask `registry.get_news_provider(provider_name)` to resolve the active or default provider.
*Alternative considered:* Just injecting the provider registry into routes. *Rejected* to maintain consistency with `PriceService`, `CompanyService`, and `OptionsService`.

### D2: Database Storage for Defaults
We will add a `system_settings` table to the existing SQLite `keys.db` managed by the `KeyRepository` or a new `SettingsRepository`. The table will store key-value pairs (e.g., `default_price_provider=ibkr`).
*Alternative considered:* Storing in a JSON file. *Rejected* because SQLite is already established and volume-mounted for persistence.

### D3: Hot-Reload of Defaults
`ProviderRegistry.reload_from_config()` will be updated to also query the new `SettingsRepository` and update its `default_*_provider` attributes.
*Alternative considered:* Resolving defaults dynamically on every request. *Rejected* because caching them in the registry is more efficient and consistent with how provider configurations are cached.

### D4: Admin UI Dropdowns
The Admin UI will query `GET /api/admin/settings/capabilities` (or similar) which returns a list of providers available for each category (prices, options, companies, news) to populate the select dropdowns.

## Risks / Trade-offs

- **Risk: Default provider is disabled.**
  - **Mitigation:** The `ProviderRegistry._resolve_default` already handles falling back to the first available valid provider if the configured default is missing or does not implement the required base class. This logic will be extended to validate DB-configured defaults.

## Migration Plan

1. **Database:** Add initialization logic to create the `system_settings` table in SQLite.
2. **Backend:** Implement `NewsService` and refactor `routes_companies.py`.
3. **Backend:** Implement the `SettingsRepository` and the `/api/admin/settings` endpoints.
4. **Frontend:** Add the System Defaults section to the Admin UI.
