## 1. Registry — Remove Hardcoded Defaults

- [x] 1.1 In `app/providers/registry.py`, change `DEFAULT_PROVIDER_FALLBACKS` (lines 36–41): set all four keys to `None` — `"default_price_provider": None`, `"default_options_provider": None`, `"default_company_provider": None`, `"default_news_provider": None`
- [x] 1.2 Change the four `default_*` instance attribute type annotations on `ProviderRegistry` to `str | None`
- [x] 1.3 Update `__init__` (lines 58–61): set all four to `None` initially (they are overwritten by `_apply_default_settings` immediately anyway)

## 2. Registry — `_resolve_default` Returns None

- [x] 2.1 Update `_resolve_default(self, configured_name, required_base, type_label)` to return `Optional[str]`
- [x] 2.2 When `configured_name is None` or the named provider is not loaded: return `None` immediately (do not walk all providers for a fallback — except news, see 2.3)
- [x] 2.3 Remove the "walk all providers to find first capable" fallback logic for **all four** provider types — news included

## 3. Registry — Provider Getters Raise 503

- [x] 3.1 Update `get_price_provider(self, name=None)`: if `name is None` and `self.default_price_provider is None` → raise `AppError(503, "No price provider configured — enable a provider in the admin UI")`
- [x] 3.2 Update `get_options_provider(self, name=None)`: same pattern with `"options provider"`
- [x] 3.3 Update `get_company_provider(self, name=None)`: same pattern with `"company data provider"`
- [x] 3.4 Update `get_news_provider(self, name=None)`: same pattern as other getters — raise `AppError(503, "No news provider configured — enable a provider in the admin UI")` when default is `None`; explicit `?provider=mock` still works
- [x] 3.5 Verify that explicitly named provider requests (e.g. `?provider=ibkr`) bypass the default check — they look up by name directly and raise `InvalidProviderError` if not loaded/enabled

## 4. DB Seed — First-Run Initial State

- [x] 4.1 Identify where `ProviderRuntimeConfig` rows are first written on startup — locate the `reload_from_config` call path that creates new provider rows
- [x] 4.2 In that path: when writing a new `ProviderRuntimeConfig` row for a provider that has no existing row, write `enabled=False` for **all** providers including mock
- [x] 4.3 Add system settings seed: in `reload_from_config` (or `SettingsRepository`), if any `default_*` key does not exist in the DB → write `None` as the value for each missing key
- [x] 4.4 Ensure seed is idempotent — running `reload_from_config` multiple times must not reset user-configured values

## 5. Tests — Registry Behaviour

- [x] 5.1 Add test: fresh registry with no DB settings → `get_price_provider()` raises `AppError(503)`
- [x] 5.2 Add test: fresh registry with no DB settings → `get_options_provider()` raises `AppError(503)`
- [x] 5.3 Add test: fresh registry with no DB settings → `get_company_provider()` raises `AppError(503)`
- [x] 5.4 Add test: fresh registry with no DB settings → `get_news_provider()` raises `AppError(503)`
- [x] 5.5 Add test: registry with `default_price_provider="ibkr"` in DB settings → `get_price_provider()` returns IBKR instance
- [x] 5.6 Update existing tests that create a registry and rely on the `ibkr` default: explicitly set `default_price_provider="ibkr"` or pass provider name in the call

## 6. Verification

- [x] 6.1 Run `uv run ruff check app/` — no lint errors
- [x] 6.2 Run `uv run pytest --maxfail=1 --disable-warnings` — all tests pass including updated registry tests
- [x] 6.3 Manual smoke: start fresh with empty `keys.db` → `GET /api/prices/AAPL` returns 503; `GET /api/news/AAPL` also returns 503
- [x] 6.4 Manual smoke: enable IBKR in admin UI → `GET /api/prices/AAPL` now routes to IBKR
