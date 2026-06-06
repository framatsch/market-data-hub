# Proposal: System Defaults & News Service

## Context
The Market Data Hub supports multiple providers for prices, options, companies, and news. Currently, the "default" provider for each service type is statically defined via environment variables (`DEFAULT_PRICE_PROVIDER`, etc.) and evaluated at startup.
Furthermore, while `CompanyService`, `OptionsService`, and `PriceService` exist, there is no `NewsService` wrapping the `BaseNewsProvider`, resulting in inconsistent usage (e.g., `routes_companies.py` injecting the provider directly).

## Why
System administrators need to be able to change default providers at runtime without restarting the application or changing environment variables. Integrating this into the Admin UI ensures full operational control.
Wrapping `BaseNewsProvider` in a dedicated `NewsService` aligns the architecture and allows the service layer to handle default resolution consistently.

## What
- **Backend:**
  - Create `app/services/news_service.py` to wrap `BaseNewsProvider`.
  - Update `app/api/routes_companies.py` to use `NewsServiceDep` instead of `NewsProviderDep`.
  - Introduce a `system_settings` table in SQLite (`keys.db`) to store runtime defaults (e.g., `default_price_provider`, `default_news_provider`).
  - Update `ProviderRegistry` to load and apply these defaults from the database during `reload_from_config()`.
  - Add Admin API endpoints (`GET /api/admin/settings`, `PUT /api/admin/settings`) to manage defaults.

- **Frontend (Admin UI):**
  - Create a new "System Defaults" settings panel (either as a new page or added to the Dashboard/Providers page).
  - Dynamically populate dropdowns for each category (Prices, Options, Companies, News) by inspecting which enabled providers implement the respective base classes.

## Impact
- Dynamic routing of default requests without server restarts.
- Consistent Service Layer architecture across all four data domains.
- Requires minor database migration (creating a new table in the existing SQLite database).
