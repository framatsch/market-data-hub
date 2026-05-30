## 1. Implement Fallback Logic in ProviderRegistry

- [x] 1.1 In `app/providers/registry.py`, add instance variables to `ProviderRegistry` for `default_price_provider`, `default_company_provider`, and `default_options_provider`.
- [x] 1.2 In `ProviderRegistry._initialize_providers`, add logic to check if `settings.DEFAULT_PRICE_PROVIDER` exists in `self._providers`. If not, find the first loaded provider that inherits from `BasePriceProvider` and set it as the default. Log a `WARNING` if a fallback is used.
- [x] 1.3 Repeat the fallback logic for `DEFAULT_COMPANY_PROVIDER` (checking against `BaseCompanyProvider`).
- [x] 1.4 Repeat the fallback logic for `DEFAULT_OPTIONS_PROVIDER` (checking against `BaseOptionsProvider`).

## 2. Update Provider Retrieval Logic

- [x] 2.1 Update `ProviderRegistry.get_price_provider` to use `self.default_price_provider` instead of reading `settings.DEFAULT_PRICE_PROVIDER` directly.
- [x] 2.2 Update `ProviderRegistry.get_company_provider` to use `self.default_company_provider` instead of reading `settings.DEFAULT_COMPANY_PROVIDER` directly.
- [x] 2.3 Update `ProviderRegistry.get_options_provider` to use `self.default_options_provider` instead of reading `settings.DEFAULT_OPTIONS_PROVIDER` directly.
- [x] 2.4 Update `ProviderRegistry.get_news_provider` to also use a resolved default (falling back to "finnhub" or "lseg") and avoid hardcoding the default inline.

## 3. Update Meta API

- [x] 3.1 Update `app/api/routes_meta.py` (`list_providers` endpoint) to return the actual dynamically resolved defaults from the registry instead of statically reading from `settings`.

## 4. Tests

- [x] 4.1 Create a unit test `tests/unit/test_registry_fallback.py` to verify that if `ENABLED_PROVIDERS` is "lseg" but `DEFAULT_PRICE_PROVIDER` is "ibkr", the registry correctly falls back to "lseg" and logs a warning.
- [x] 4.2 Verify that requesting a provider for a capability that isn't loaded (e.g., options provider when only lseg is enabled) correctly throws an `InvalidProviderError` rather than crashing.