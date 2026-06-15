## 1. NewsService Wrapper & Dependency Injection

- [x] 1.1 Create `app/services/news_service.py` with `NewsService` class wrapping `BaseNewsProvider` and querying `get_registry().get_news_provider()`.
- [x] 1.2 Update `app/dependencies.py` to add `NewsServiceDep` (returning `news_service`) and keep/remove `NewsProviderDep` as needed.
- [x] 1.3 Refactor `app/api/routes_companies.py` to inject `NewsServiceDep` and call `service.get_company_news` instead of directly calling the provider.
- [x] 1.4 Write unit tests for `NewsService` verifying it resolves the correct provider from the registry.

## 2. System Settings Repository

- [x] 2.1 Create `app/admin/settings_repository.py` and add logic to initialize the `system_settings` table (columns: `key`, `value`, `updated_at`) in `keys.db`.
- [x] 2.2 Implement `SettingsRepository.get(key)`, `SettingsRepository.set(key, value)`, and `SettingsRepository.get_all()` using `asyncio.to_thread`.
- [x] 2.3 Initialize `SettingsRepository` singleton during the FastAPI lifespan in `app/main.py`.
- [x] 2.4 Write unit tests for `SettingsRepository`.

## 3. ProviderRegistry Hot-Reload Updates

- [x] 3.1 Update `ProviderRegistry.reload_from_config()` to optionally accept `SettingsRepository` (or resolve it via runtime globals) and fetch `system_settings`.
- [x] 3.2 In `reload_from_config()`, override environment defaults (`DEFAULT_PRICE_PROVIDER`, etc.) with values from the database if they exist and are valid.
- [x] 3.3 Ensure the `ProviderRegistry` fallback logic handles invalid database defaults gracefully.

## 4. Admin API for Settings & Capabilities

- [x] 4.1 Implement `GET /api/admin/settings/defaults` in `app/api/routes_admin.py` to return the current system defaults. Secure with `_principal: PrincipalDep`.
- [x] 4.2 Implement `PUT /api/admin/settings/defaults` to update the defaults in `system_settings` and trigger `registry.reload_from_config()`. Secure with `_principal: PrincipalDep`.
- [x] 4.3 Implement `GET /api/admin/settings/capabilities` in `app/api/routes_admin.py` to return a map of enabled providers and their implemented capabilities. Secure with `_principal: PrincipalDep`.
- [x] 4.4 Write unit tests for the new `/api/admin/settings/*` endpoints.

## 5. Admin UI - API and Types

- [x] 5.1 Update `admin/src/types.ts` to include `SystemDefaults` and `ProviderCapabilities` interfaces.
- [x] 5.2 Add queries for `GET /api/admin/settings/defaults` and `GET /api/admin/settings/capabilities` to the frontend using TanStack Query.
- [x] 5.3 Add mutation for `PUT /api/admin/settings/defaults` with proper cache invalidation.

## 6. Admin UI - System Defaults Panel

- [x] 6.1 Create `admin/src/pages/SettingsPage.tsx` to host the global system defaults.
- [x] 6.2 Update `admin/src/router.tsx` to include the `/admin/settings` route.
- [x] 6.3 Update `admin/src/layout/Sidebar.tsx` to include a navigation link for Settings.
- [x] 6.4 Implement the settings form with 4 dropdowns (Prices, Options, Companies, News), dynamically populated using the capabilities API.
- [x] 6.5 Connect the form submit to the mutation to save changes and show success/error snackbars.
- [x] 6.6 Verify building the frontend (`npm run build`) works successfully.

## 7. Legacy Configuration Cleanup

- [x] 7.1 Remove `DEFAULT_PRICE_PROVIDER`, `DEFAULT_COMPANY_PROVIDER`, `DEFAULT_OPTIONS_PROVIDER`, and `DEFAULT_NEWS_PROVIDER` from `app/config.py`.
- [x] 7.2 Remove references to these variables from `ProviderRegistry` fallback logic, replacing them with static fallback strings (e.g. `"ibkr"` or `"finnhub"`) when the database is empty.
- [x] 7.3 Remove the environment variables from `.env.example` and the `README.md` documentation.
