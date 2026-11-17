## ADDED Requirements

### Requirement: Earnings provider capability
The system SHALL define `BaseEarningsProvider` with `get_upcoming_earnings(start, end, roots)` returning upcoming events with report dates within `start`…`end` inclusive for the given roots or, when `roots` is `None`, for every symbol the provider covers; `get_earnings_history(root)` returning the reported events of one root; and `test_connection()`, and SHALL declare `earnings_upcoming` (default `True`) stating whether it delivers upcoming events. The registry SHALL list enabled providers implementing it under the capability `earnings` and SHALL resolve requests through `default_earnings_provider` or the `provider` query parameter.

#### Scenario: Provider listed under earnings
- **WHEN** Alpha Vantage is enabled and `GET /providers` is called
- **THEN** the `earnings` list contains `alphavantage`

#### Scenario: No earnings provider configured
- **WHEN** no default earnings provider is configured and `GET /earnings/next?symbols=AAPL` is called without `provider`
- **THEN** the response is HTTP 503 with `detail: "No earnings provider configured — enable a provider in the admin UI"`

#### Scenario: Provider without the capability
- **WHEN** `GET /earnings/calendar?symbols=AAPL&provider=schwab` is called
- **THEN** the response is HTTP 400 `INVALID_PROVIDER` naming `schwab`

### Requirement: Earnings event model
Every earnings event SHALL carry `symbol` (canonical), `report_date`, `report_time` (`bmo`, `amc`, `during` or `unknown`), `date_status` (`confirmed`, `projected` or `unknown`), `reported` (boolean), `provider` and `updated_at`, and MAY carry `fiscal_period_end`, `eps_estimate`, `eps_actual`, `eps_surprise`, `eps_surprise_pct` and `currency`. `date_status` SHALL reflect only what the provider states, except that reported events SHALL be `confirmed`; the system SHALL NOT estimate, extrapolate or default a report date. `reported` SHALL be true when `report_date` is before today in New York or `eps_actual` is present.

#### Scenario: Provider does not state confirmation
- **WHEN** the provider delivers an upcoming event without any confirmation information
- **THEN** the event has `date_status: "unknown"`

#### Scenario: Release time unknown
- **WHEN** the provider delivers no release time
- **THEN** the event has `report_time: "unknown"`

#### Scenario: Past event without actual EPS
- **WHEN** an event lies three days in the past and the provider has no actual EPS yet
- **THEN** the event has `reported: true` and `eps_actual: null`

### Requirement: Earnings calendar endpoint
`GET /earnings/calendar` SHALL accept `symbols` (comma-separated, 1–50 after de-duplication), `from`, `to` (dates, defaults today − 30 days and today + 90 days, range at most 800 days), `provider` and `format` (`json` or `csv`). It SHALL return the events of all requested stocks in the range, sorted by `report_date` and then `symbol`, and `meta.symbols` with one entry per requested symbol holding `symbol`, `status` (`ok`, `not_applicable`, `not_found` or `error`), `history` (`complete`, `pending` or `not_requested`) and an optional `message`. Upcoming events SHALL come from the provider's calendar, which SHALL be requested for all symbols together, not once per symbol. Past events SHALL come from the per-symbol history.

#### Scenario: Watchlist calendar
- **WHEN** `GET /earnings/calendar?symbols=AAPL,MSFT,SPY&from=2026-11-17&to=2027-02-28` is requested
- **THEN** the response contains the AAPL and MSFT events in the range sorted by date, `meta.symbols` marks `SPY` as `not_applicable`, and at most one calendar request was sent to the provider

#### Scenario: Too many symbols
- **WHEN** 51 distinct symbols are requested
- **THEN** the response is HTTP 422 and no provider is called

#### Scenario: Non-stock symbol type
- **WHEN** `symbols=I:SPX,AAPL` is requested
- **THEN** the response is HTTP 422 naming `I:SPX`

#### Scenario: History budget used up
- **WHEN** a range reaching into the past is requested for 30 symbols without stored history and the budget allows 20 more requests today
- **THEN** history is fetched for the first 20 symbols in request order, the other 10 have `history: "pending"` and their upcoming events, and the response is HTTP 200

#### Scenario: CSV export
- **WHEN** `format=csv` is requested
- **THEN** the response is a CSV attachment with one row per event and the `X-MDH-Data-As-Of` header

### Requirement: Next earnings endpoint
`GET /earnings/next` SHALL accept `symbols` (1–50) and `provider` and SHALL return one row per requested symbol in request order with `symbol`, `event` (the earliest event with `report_date` on or after today in New York, or `null`), `days_until` (calendar days from today in New York, `null` without event), `last_reported` (the latest stored reported event of the symbol, or `null` when none is stored), `status` and `message`. It SHALL be answered from the provider's calendar only and SHALL NOT request per-symbol history. `status` SHALL be `ok` with an event, `none_scheduled` when the calendar was loaded but has no event for the symbol (for example because the company has not announced its date yet), `not_applicable` for ETFs, and `error` when the calendar could not be obtained. The endpoint SHALL return HTTP 200 unless the calendar could not be obtained and nothing is stored, in which case it SHALL return the provider error.

#### Scenario: Next earnings for a watchlist
- **WHEN** today is 2026-11-17, AAPL reports on 2027-01-28 and `GET /earnings/next?symbols=MSFT,AAPL` is requested
- **THEN** the rows are in the order MSFT, AAPL and the AAPL row has `days_until: 72`

#### Scenario: Report today
- **WHEN** a symbol reports today after the close
- **THEN** its row has the event with `report_time: "amc"` and `days_until: 0`

#### Scenario: ETF in the list
- **WHEN** `symbols=SPY,AAPL` is requested
- **THEN** the SPY row has `event: null` and `status: "not_applicable"`

#### Scenario: Date not announced yet
- **WHEN** the calendar has no event for AAPL and AAPL's history is stored
- **THEN** the AAPL row has `event: null`, `status: "none_scheduled"` and `last_reported` with the latest reported quarter

#### Scenario: No history requests
- **WHEN** `GET /earnings/next` is requested for 25 symbols without stored history
- **THEN** at most one calendar request and no history request is sent to the provider

#### Scenario: Provider down without stored calendar
- **WHEN** the calendar request fails and no calendar is stored
- **THEN** the response carries the provider error status code

### Requirement: Company earnings endpoint
`GET /companies/{symbol}/earnings` SHALL return the reported and upcoming events of one stock with `from` and `to` defaulting to today − 1095 days and today + 400 days, sorted by `report_date` ascending, with `provider` and `format` like the calendar endpoint. An ETF SHALL be answered with HTTP 422 `CAPABILITY_NOT_SUPPORTED` without a provider call; a symbol for which the provider knows neither history nor upcoming events SHALL be answered with HTTP 404.

#### Scenario: Earnings history of a stock
- **WHEN** `GET /companies/AAPL/earnings` is requested
- **THEN** the response lists past events with EPS estimate, actual and surprise and the upcoming events, oldest first

#### Scenario: ETF
- **WHEN** `GET /companies/SPY/earnings` is requested
- **THEN** the response is HTTP 422 `CAPABILITY_NOT_SUPPORTED`

### Requirement: Upcoming and reported event reconciliation
An upcoming event and a reported event of the same symbol, provider and `fiscal_period_end` SHALL be returned as one event; the reported event's values SHALL win once it has an actual EPS.

#### Scenario: Report arrives
- **WHEN** the calendar holds AAPL for fiscal period end 2026-12-31 on 2027-01-28 and the history later returns that quarter with `reportedEPS`
- **THEN** responses contain one AAPL event for that quarter with the reported values and `reported: true`

### Requirement: Response metadata
Every earnings response SHALL carry `meta.provider`, `meta.data_as_of` (the oldest time at which the system obtained any included data from the provider) and `meta.stale` (true when stored events were served because the provider failed or its request budget was exhausted).

#### Scenario: Served from a fresh store
- **WHEN** the calendar was synchronised two hours ago and the requested symbols need no history
- **THEN** no provider call is made, `meta.stale` is false and `meta.data_as_of` is the calendar's synchronisation time

### Requirement: Stored earnings events
When the history store is enabled (`DATABASE_URL`), the system SHALL store earnings events per provider, canonical symbol and report date with their source (`calendar` or `history`), and SHALL track per provider the calendar's covered range and synchronisation times and per provider and symbol the history's synchronisation times. A calendar synchronisation SHALL store the events of every symbol the provider returns and SHALL, in one transaction, replace the provider's `calendar` events in the covered range. A history synchronisation SHALL insert or update the symbol's reported events. Events of different providers SHALL never be mixed.

#### Scenario: Report date moved
- **WHEN** the stored calendar has AAPL on 2027-01-28 and the next calendar synchronisation returns AAPL on 2027-01-30
- **THEN** the store holds only the event on 2027-01-30 for AAPL from that provider

#### Scenario: Calendar covers unrequested symbols
- **WHEN** a calendar synchronisation triggered by a request for AAPL returns events for 4,000 symbols
- **THEN** a later `GET /earnings/next?symbols=NVDA` is answered from the store without a provider call

#### Scenario: Provider isolation
- **WHEN** events of AAPL are stored for two providers
- **THEN** a request with `provider=alphavantage` returns only Alpha Vantage events

### Requirement: Request-driven earnings refresh
A request SHALL synchronise the calendar only when its last successful synchronisation is older than `EARNINGS_CALENDAR_RESYNC_HOURS` (default 24) or the requested range exceeds its covered range. It SHALL synchronise a symbol's history only when the request needs dates before today and the symbol has no history synchronisation, or when a stored event of the symbol dated within the last `EARNINGS_ACTUALS_WINDOW_DAYS` (default 10) has no `eps_actual` and the history was synchronised more than 12 hours ago. After a failed synchronisation the same calendar or symbol SHALL NOT be retried for `EARNINGS_RETRY_MINUTES` (default 30).

#### Scenario: Fresh calendar is not refetched
- **WHEN** the calendar was synchronised 3 hours ago
- **THEN** `GET /earnings/next` for any stocks makes no provider call

#### Scenario: Waiting for the actual EPS
- **WHEN** AAPL reported two days ago, its stored event has no `eps_actual` and its history was synchronised 13 hours ago
- **THEN** the next request that includes AAPL's past synchronises AAPL's history

#### Scenario: Retry pause after failure
- **WHEN** a calendar synchronisation failed 10 minutes ago
- **THEN** a request serves the stored calendar and makes no provider call

### Requirement: Earnings without the store
When the history store is disabled or failing open, the system SHALL keep the provider's parsed calendar in Redis for `EARNINGS_CALENDAR_RESYNC_HOURS` and SHALL obtain history per request through the response cache; without Redis it SHALL call the provider within its request budget. `meta.stale` SHALL be false in this mode.

#### Scenario: Two watchlists without database
- **WHEN** `DATABASE_URL` is unset and two different `GET /earnings/next` requests arrive within an hour
- **THEN** the provider calendar is requested once

### Requirement: Stored earnings on provider failure
When the provider fails or its request budget is exhausted and stored events exist for the requested symbols, the system SHALL return the stored events with `meta.stale = true` instead of an error. When the store is disabled or holds nothing for a symbol, that symbol SHALL get the error (batch endpoints) or the request SHALL fail with it (company endpoint).

#### Scenario: Budget exhausted
- **WHEN** the Alpha Vantage budget of the day is exhausted, the calendar is due for refresh and a calendar is stored
- **THEN** `GET /earnings/next?symbols=AAPL` returns the stored next event with `meta.stale: true`

#### Scenario: Store disabled
- **WHEN** `DATABASE_URL` is unset and the provider fails
- **THEN** `GET /companies/AAPL/earnings` returns the provider error

### Requirement: Fail-open storage
A database error while reading or writing earnings events SHALL NOT fail the request; the system SHALL answer as if the store were disabled, following the fail-open rule of the history store.

#### Scenario: Database unreachable
- **WHEN** PostgreSQL is unreachable and `GET /earnings/next?symbols=AAPL` is requested
- **THEN** the system answers from the provider or the Redis calendar and logs one warning

### Requirement: Earnings MCP tools
The MCP server SHALL provide `get_earnings_calendar` (arguments `symbols`, optional `from_date`, `to_date`, `provider`) and `get_next_earnings` (arguments `symbols`, optional `provider`) returning the same data as the HTTP endpoints through the same service, storage and cache policy.

#### Scenario: Next earnings via MCP
- **WHEN** an MCP client calls `get_next_earnings` with `symbols: ["AAPL", "SPY"]`
- **THEN** the result has one row per symbol with the same fields and statuses as `GET /earnings/next`
