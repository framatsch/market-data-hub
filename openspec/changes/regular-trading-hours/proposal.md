## Why

Intraday historical price data currently includes extended hours (pre-market and after-hours trading) for some providers like Polygon, which can distort technical indicators and charting for users who only want to analyze Regular Trading Hours (RTH). We need a standardized way to request only RTH data across all providers by default, while allowing explicit opt-in for extended hours data.

## What Changes

- Add a new query parameter `extended_hours: bool = False` to the `/prices/{symbol}/historical` API endpoint.
- Update `BasePriceProvider.get_historical_prices` signature to include `extended_hours`.
- Implement provider-specific logic to filter or request RTH data (IBKR via `useRTH`, Polygon/LSEG via post-processing or SDK session filters).
- **BREAKING**: Default behavior for historical intraday prices will now exclude extended hours data unless `extended_hours=true` is explicitly requested.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `historical-prices`: Changing the requirements to default to Regular Trading Hours (RTH) only, with an opt-in parameter for extended hours data.

## Impact

- **API**: `/prices/{symbol}/historical` endpoint signature change (backwards-compatible for callers not specifying the flag, but behavioral breaking change as data is now filtered by default).
- **Providers**: Changes to `ibkr.py`, `polygon.py`, and `lseg.py` to support RTH filtering.
- **Tests**: Historical pricing tests need updates to assert RTH logic.
