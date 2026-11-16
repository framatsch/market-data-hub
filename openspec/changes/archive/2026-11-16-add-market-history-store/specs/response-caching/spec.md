## ADDED Requirements

### Requirement: Day-granular keys for daily-or-longer history
For `GET /prices/{symbol}/history` with a daily-or-longer interval (`1d`, `1w`, `1wk`, `1mo`, or no interval), the cache key SHALL contain `start` and `end` reduced to their UTC calendar date (`YYYY-MM-DD`); naive values SHALL be interpreted as UTC. Keys of intraday intervals SHALL keep the full values.

#### Scenario: Moving start time
- **WHEN** `GET /prices/AAPL/history?interval=1d&start=2025-03-06T08:55:01.137706+00:00&provider=schwab` and the same request with `start=2025-03-06T12:22:29.566314+00:00` are sent
- **THEN** both resolve to `mdh:prices:history:AAPL:interval=1d&provider=schwab&start=2025-03-06` and the second is a cache hit

#### Scenario: Next day
- **WHEN** the same request is sent with a `start` on 2025-03-07
- **THEN** it resolves to a different key

#### Scenario: Intraday unchanged
- **WHEN** `interval=5m&start=2026-11-16T14:30:00Z` is requested
- **THEN** the key contains the full `start` value

### Requirement: Stale responses are never cached
A response that carries `meta.stale` `true` SHALL NOT be written to the cache and SHALL be sent with `Cache-Control: no-store`.

#### Scenario: Provider recovers
- **WHEN** a daily-history request is answered with stored bars because the provider timed out, and the provider works again for the next identical request
- **THEN** the second request calls the provider and returns a response without `meta.stale`
