## Context

The registry (`app/providers/registry.py`) has two levels of defaults:
1. `DEFAULT_PROVIDER_FALLBACKS` dict (hardcoded, lines 36–41) — `ibkr` for price/company/options, `finnhub` for news
2. `__init__` instance assignments (lines 58–61) — overwritten immediately by `_apply_default_settings()`

`_apply_default_settings` merges DB settings over `DEFAULT_PROVIDER_FALLBACKS`. `_resolve_default` validates that the configured name is loaded and satisfies the required base class; if not, it walks all providers to find the first capable one. This "silent fallback to first available" is the behaviour to eliminate.

Provider enabled/disabled state is stored in `ProviderRuntimeConfig` in SQLite. On first start there are no rows → `reload_from_config` creates them with `enabled=True` for all loaded providers. This is the behaviour to change: first-run should write `enabled=False` for all non-mock providers.

## Goals / Non-Goals

**Goals:**
- `DEFAULT_PROVIDER_FALLBACKS` changed: all four types → `None`
- `_resolve_default` returns `None` (not a fallback provider) when no capable provider is configured
- Provider getters (`get_price_provider`, `get_options_provider`, `get_company_provider`, `get_news_provider`) all raise `AppError(503, "No <type> provider configured — enable a provider in the admin UI")` when default is `None`
- DB seed on first start: **all** providers written as `enabled=False` in `ProviderRuntimeConfig`; all four `default_*` keys written as `None` in system settings if no settings row exists
- `ENABLED_PROVIDERS` env var continues to work — it controls which providers are loaded, separate from the DB enabled/disabled state

**Non-Goals:**
- Mock implementations for price, company, or options (no mock price/options/company providers)
- UI changes (503 message is returned as JSON by existing `AppError` handler)
- Changing the `ENABLED_PROVIDERS` env var semantics

## Decisions

### D1: `None` sentinel in `_resolve_default`, not a special string

Returning `None` from `_resolve_default` is cleaner than a sentinel string like `"none"`. The four `default_*` instance attributes change type to `str | None`. The getter methods guard with `if not self.default_price_provider or ...` before the `isinstance` check.

### D2: DB seed in `reload_from_config`, not in `__init__`

`__init__` runs at module import time (before the DB is available). The seed logic runs the first time `reload_from_config()` is called at app startup (after DB is ready). Seed condition: `ProviderRuntimeConfig` has no row for a given provider name → write `enabled=False` for **all** providers including mock.

### D3: System settings seed: only if no row exists

`SettingsRepository.get_system_settings()` returns `{}` on first run (no rows). The seed writes all four `default_*` keys as `None` only if the key is not already present, so user-configured values are never overwritten.

### D4: `get_news_provider` raises 503 like all other types

`MockNewsProvider` is available for explicit use via `?provider=mock` but is not injected as a default. If `default_news_provider` is `None`, the getter raises `AppError(503, "No news provider configured — enable a provider in the admin UI")` — consistent with all other provider types.

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| Existing installations that relied on the `ibkr` fallback break after update | `reload_from_config` seed only writes rows that do not exist yet — existing configured rows are untouched |
| `ENABLED_PROVIDERS=""` (all providers loaded) + no DB → all providers enabled=False → 503 everywhere | Expected and desired. User must configure via admin UI after first deploy. README should be updated to note this. |
| Tests that rely on the `ibkr` default provider may fail | Test fixtures that create a registry will need to explicitly call `enable_provider("ibkr")` or set the default in the test |
