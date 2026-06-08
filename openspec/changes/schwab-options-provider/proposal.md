## Why

`SchwabProvider` currently only inherits from `BasePriceProvider` — it cannot be used for options data. The class does not implement `get_option_chain` or `get_option_quote`, and the registry's `isinstance(provider, BaseOptionsProvider)` check rejects it entirely, returning HTTP 503 for any options request directed at Schwab. Schwab's brokerage API (via schwab-py's `client.get_option_chain()`) fully supports options chains including greeks, so this is a gap in available capability rather than a platform limitation.

## What Changes

- **`SchwabProvider`** gains `BaseOptionsProvider` as a second base class
- **`get_option_chain()`** implemented using schwab-py's `client.get_option_chain()` with contract-type enum mapping (`right` → `Client.Options.ContractType.ALL/CALL/PUT`) and expiry date filtering via `from_date=expiry, to_date=expiry`
- **`get_option_quote()`** implemented using `client.get_quotes([option_id])` with OCC symbol lookup; falls back to a narrowed chain call if the quote endpoint does not return greeks
- **`_parse_option_chain()`** private helper that maps the Schwab `callExpDateMap`/`putExpDateMap` nested-dict response format to `List[OptionQuote]`, handling the `"YYYY-MM-DD:DTE"` key format, the `"volatility"` field name for IV (not `"impliedVolatility"`), and the `last=0 → mark` fallback for price
- **Unit tests** added to `tests/unit/test_schwab_provider.py` covering the new methods

## Capabilities

### New Capabilities

- `schwab-options`: Schwab options chain and single-option-quote retrieval via the schwab-py client, mapped to the `BaseOptionsProvider` interface

### Modified Capabilities

- `configurable-providers`: `SchwabProvider` now satisfies the `BaseOptionsProvider` interface check in the registry, making it available as an options provider when selected via the admin UI

## Impact

- **`app/providers/schwab.py`**: class declaration, imports, 3 new methods
- **`tests/unit/test_schwab_provider.py`**: new test cases (no existing tests broken)
- **`app/providers/registry.py`**: no changes — `"schwab"` is already in `provider_classes`; the `isinstance` check passes automatically once the base class is added
- **No DB migration, no API changes, no frontend changes**
