## Why

On a fresh installation, the registry falls back to hardcoded defaults: `ibkr` for price/company/options and `finnhub` for news. This means a newly deployed instance silently tries to use IBKR and Finnhub even when no credentials are configured, resulting in misleading connection errors or degraded-state behaviour instead of a clear "not configured" message.

The intended first-run experience: the user sees all providers as disabled, configures credentials for the ones they want, enables them through the admin UI, and that action makes them the active providers. No provider should be silently assumed.

## What Changes

- **Registry `DEFAULT_PROVIDER_FALLBACKS`**: all four defaults changed to `None`. No provider is assumed on a fresh install.
- **`MockNewsProvider`** remains available for explicit use but is not a default. For all four provider types — price, company, options, news — if no provider is configured, the API returns HTTP 503 with a clear message.
- **Registry `_resolve_default`**: when no capable provider exists for a given type, return `None` (or a sentinel) instead of logging an error and returning the invalid name. The getter methods (`get_price_provider`, `get_options_provider`, etc.) raise `AppError(503, "No <type> provider configured — enable a provider in the admin UI")` when the resolved default is `None`.
- **DB seed on first start**: `SettingsRepository` writes initial default values on first run (`default_price_provider=None`, `default_options_provider=None`, `default_company_provider=None`, `default_news_provider=None`). All providers are stored as `enabled=false` in `ProviderRuntimeConfig` if not already present.
- **`ENABLED_PROVIDERS` env var** behaviour unchanged — explicit env-based enabling still works for Docker/CI scenarios.

## Capabilities

### New Capabilities

- `provider-no-default`: API endpoints return HTTP 503 with actionable error message when no provider of the required type is enabled/configured, instead of silently failing or using an unconfigured provider

### Modified Capabilities

- `configurable-providers`: Initial provider state changes — all providers start disabled except mock; default provider for each type is `None` (not `ibkr`/`finnhub`)

## Impact

- **`app/providers/registry.py`**: `DEFAULT_PROVIDER_FALLBACKS`, `_resolve_default`, `get_price_provider`, `get_options_provider`, `get_company_provider`, `get_news_provider` — error path changed
- **`app/utils/errors.py`**: no new error type needed — existing `AppError` with 503 is sufficient
- **`app/api/routes_*.py`**: no changes — provider getter already raises, FastAPI exception handler already maps `AppError` to HTTP
- **`app/repositories/` (SettingsRepository or similar)**: seed logic on first run
- **No frontend changes, no DB migration** (new rows written on first start, not a schema change)
