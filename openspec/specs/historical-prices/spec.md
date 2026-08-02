# historical-prices Specification

## Purpose
TBD - created by archiving change regular-trading-hours. Update Purpose after archive.
## Requirements
### Requirement: Regular Trading Hours Filtering
The system SHALL return only Regular Trading Hours (RTH) data by default for intraday historical prices. The user MAY request extended hours data by explicitly passing `extended_hours=true`.

#### Scenario: Requesting intraday data without extended_hours flag
- **WHEN** a client requests intraday historical data (`/prices/{symbol}/historical?interval=1m`)
- **THEN** the system MUST filter and return only data points that fall within US Regular Trading Hours (09:30 - 16:00 ET).

#### Scenario: Requesting intraday data with extended_hours=true
- **WHEN** a client requests intraday historical data with the flag explicitly set to true (`/prices/{symbol}/historical?interval=1m&extended_hours=true`)
- **THEN** the system MUST return all available data, including pre-market and after-hours data points.

#### Scenario: Requesting daily data
- **WHEN** a client requests daily or larger interval data (`/prices/{symbol}/historical?interval=1d`)
- **THEN** the system MUST NOT apply the RTH intraday filter, as daily bars represent the full day's aggregate.

