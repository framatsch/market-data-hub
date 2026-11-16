## MODIFIED Requirements

### Requirement: IV Rank and IV Percentile endpoint
The system SHALL expose `GET /volatility/{symbol}/stats` returning a `VolatilityStats` with the fields `symbol`, `sec_type`, `source_instrument`, `tenor_days`, `provider`, `window`, `window_points`, `window_start`, `window_end`, `current`, `min`, `max`, `iv_rank` and `iv_percentile`.

The service layer SHALL compute the values from the IV history of the effective provider over the last `window` daily points, independent of the provider:
- `current` is the `iv` of the most recent point.
- `iv_rank` = (current − min) / (max − min) × 100.
- `iv_percentile` = the share of window points, excluding the current one, that are strictly below `current`, × 100.
- `iv_rank` and `iv_percentile` SHALL be rounded to 2 decimals.

With the history store enabled, the points SHALL be read from the store as specified by `market-history-store`: the provider is called only for days the series does not cover, and when the provider fails while the store holds at least 20 usable points of that provider for the window, the statistics SHALL be computed from the stored points and returned with `meta.stale` `true`. Points of another provider SHALL never be used. With the store disabled or unavailable, the points SHALL be loaded from the provider for each request.

The endpoint SHALL accept `window` (integer 20–756, default 252), `tenor_days` (30, 60 or 90, default 30), `sec_type`, `ric`, `provider` and `format`.

#### Scenario: Default 52-week stats
- **WHEN** a client calls `GET /volatility/AAPL/stats`
- **THEN** the system SHALL use enough 30-day-tenor history to cover 252 trading days and return `window` 252, `window_points` ≤ 252, and `iv_rank` and `iv_percentile` between 0 and 100

#### Scenario: Correct computation
- **WHEN** the window contains the values 0.20, 0.10, 0.30, 0.25 (oldest to newest)
- **THEN** `current` SHALL be 0.25, `min` 0.10, `max` 0.30, `iv_rank` 75.00 and `iv_percentile` 66.67

#### Scenario: Flat window
- **WHEN** all points in the window have the same value
- **THEN** `iv_rank` SHALL be `null` and `iv_percentile` SHALL be 0

#### Scenario: Insufficient history
- **WHEN** fewer than 20 usable points are available
- **THEN** the system SHALL respond with HTTP 404, code `DATA_NOT_FOUND` and `details.reason` `insufficient_history`

#### Scenario: Window out of range
- **WHEN** a client calls the stats endpoint with `window=5`
- **THEN** the system SHALL respond with HTTP 422

#### Scenario: Stats from stored points
- **WHEN** the store covers the window through the newest closed day and `GET /volatility/AAPL/stats` is requested while the market is settled
- **THEN** the statistics are returned without a provider call and equal those computed from the same points loaded from the provider

#### Scenario: Provider unreachable with stored history
- **WHEN** the volatility provider cannot be reached and the store holds 252 points ending two days ago
- **THEN** the response is `200` with `window_end` two days ago and `meta.stale` `true`

#### Scenario: Provider unreachable without stored history
- **WHEN** the volatility provider cannot be reached and the store holds fewer than 20 points for the symbol
- **THEN** the provider error is returned with its usual status code
