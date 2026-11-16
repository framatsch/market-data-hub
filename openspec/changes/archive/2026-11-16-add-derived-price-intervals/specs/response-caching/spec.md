## ADDED Requirements

### Requirement: Normalized interval in price history keys
For `GET /prices/{symbol}/history` and the MCP tool for historical prices, the cache key SHALL contain the interval in its normalized form as defined by `derived-price-intervals` (lower case, `60m` as `1h`, `1wk` as `1w`). The rules that depend on the interval, namely the day-granular `start` and `end` of daily-or-longer history and the bar-state-aware lifetime, SHALL be applied to the normalized interval. An interval that cannot be normalized SHALL keep its given value in the key.

#### Scenario: Alias shares the entry
- **WHEN** `GET /prices/AAPL/history?interval=1wk&start=2025-03-06&provider=ibkr` and the same request with `interval=1w` are sent
- **THEN** both resolve to `mdh:prices:history:AAPL:interval=1w&provider=ibkr&start=2025-03-06` and the second is a cache hit

#### Scenario: Upper-case weekly interval is day-granular
- **WHEN** `interval=1W&start=2025-03-06T08:55:01+00:00` is requested
- **THEN** the key contains `interval=1w` and `start=2025-03-06`

#### Scenario: Derived interval
- **WHEN** `interval=4h` is requested from Schwab and derived from `30m`
- **THEN** the key contains `interval=4h`, not the source interval
