## Why

The Market Data Hub currently retrieves historical price data exclusively through IBKR and LSEG providers. Adding Schwab as a third historical-price source gives users a low-barrier alternative — Schwab accounts are common among retail traders, the `schwab-py` library provides a clean async interface, and Schwab's API offers daily/weekly OHLCV back to 1985 with no extra market-data subscription needed beyond a standard brokerage account.

## What Changes

- New `SchwabProvider` class in `app/providers/schwab.py` implementing `BasePriceProvider` with `get_last_price` and `get_historical_prices`.
- New `SCHWAB_*` config keys in `app/config.py` and `.env.example`.
- `SchwabProvider` registered in `app/providers/registry.py` under the key `"schwab"`.
- `get_historical_prices` supports all intraday intervals (1m, 5m, 10m, 15m, 30m) and daily/weekly granularity by mapping to the appropriate `schwab-py` convenience method.
- Unit tests added in `tests/unit/test_schwab_provider.py` using mocked `httpx` responses.
- Diagnostic script added at `scripts/diagnostics/test_schwab_connection.py`.

## Capabilities

### New Capabilities

- `schwab-price-history`: Fetch OHLCV bars for US equity symbols via the Schwab Individual Trader API using `schwab-py`. Covers per-minute through weekly granularity, configurable date ranges, and optional extended-hours data.

### Modified Capabilities

_(none — no existing spec-level requirement changes)_

## Impact

- **`app/providers/schwab.py`** — new file; all Schwab logic lives here.
- **`app/providers/registry.py`** — one new entry in the price-provider factory.
- **`app/config.py`** — five new `SCHWAB_*` settings; backward-compatible (all default to empty/disabled).
- **`.env.example`** — new section documenting Schwab credentials.
- **`pyproject.toml`** — add `schwab-py` to dependencies if not already present.
- **No breaking changes** to existing endpoints or providers.
- Schwab provider is opt-in: missing `SCHWAB_API_KEY` keeps it disabled and raises `ProviderConnectionError` only when explicitly requested.
