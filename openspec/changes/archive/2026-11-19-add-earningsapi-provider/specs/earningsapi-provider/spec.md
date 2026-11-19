## ADDED Requirements

### Requirement: EarningsAPI provider registration
The system SHALL provide a provider `earningsapi` that implements `BaseEarningsUpcomingProvider` (`upcoming_mode = "symbol"`, `earnings_day_calendar = true`) and `BaseEarningsHistoryProvider`. It SHALL be part of the known providers, disabled by default, enabled and configured in the Admin UI like other providers, and SHALL send its credential `api_key` from the encrypted key store as query parameter `apikey` to `https://api.earningsapi.com`. `GET /api/admin/providers` SHALL list its capabilities as `["earnings_upcoming", "earnings_history"]`. Its request budget (see `alphavantage-provider`) SHALL default to 100 per day and 1000 per month, the limits of the free tier.

#### Scenario: Enable with a key
- **WHEN** an admin stores an `api_key` for `earningsapi` and enables the provider
- **THEN** the registry loads it without a restart and lists it under `earnings_upcoming`, `earnings_history` and `earnings`

#### Scenario: Missing key
- **WHEN** the provider is enabled without an `api_key`
- **THEN** requests to it return HTTP 503 `PROVIDER_NOT_AVAILABLE` naming the missing credential

#### Scenario: Budget defaults
- **WHEN** the provider is enabled without budget settings
- **THEN** its usage endpoint shows a budget of 100 for the day and 1000 for the month

### Requirement: Per-symbol earnings from EarningsAPI
`get_symbol_earnings` and `get_earnings_history` SHALL both use one `GET /v2/earnings?symbol=<root>` request (one synchronisation serves both roles when EarningsAPI is the default for both). `get_symbol_earnings` SHALL return every delivered row as one event of the requested canonical symbol, `get_earnings_history` only the reported ones (`DATA_NOT_FOUND` when none is reported): `date` as `report_date`; `time` `time-pre-market` as `bmo`, `time-after-hours` as `amc`, `null` or any other value as `unknown`; `epsEstimate` as `eps_estimate`, `eps` as `eps_actual`, `revenueEstimate` as `revenue_estimate` and `revenue` as `revenue_actual`, each converted to Decimal with `null` or non-finite values as `null`; `eps_surprise` as `eps_actual − eps_estimate` and `eps_surprise_pct` as `eps_surprise / |eps_estimate| × 100` when both are present and the estimate is not zero, otherwise `null`; `fiscal_period_end` `null`; `currency` `USD`; `date_status` `confirmed` for reported events and `unknown` otherwise; `reported` per the event model. The provider SHALL NOT estimate missing dates. `get_upcoming_earnings` SHALL raise `CAPABILITY_NOT_SUPPORTED` without a request.

#### Scenario: Upcoming and reported quarters in one request
- **WHEN** today is 2026-11-18 and the per-symbol earnings of ADI are requested
- **THEN** exactly one request is sent and the result contains the event of 2026-11-24 with `reported: false`, `report_time: "bmo"`, `eps_estimate: 3.884015`, `eps_actual: null`, `revenue_estimate: 4320121322`, and the reported event of 2026-08-19 with `eps_actual: 3.45` and `eps_surprise: 0.112549`

#### Scenario: After-hours release
- **WHEN** a row has `time: "time-after-hours"`
- **THEN** the event has `report_time: "amc"`

#### Scenario: Release time missing
- **WHEN** a row has `time: null`
- **THEN** the event has `report_time: "unknown"`

#### Scenario: No date confirmation
- **WHEN** an upcoming row is delivered
- **THEN** the event has `date_status: "unknown"`

#### Scenario: Unknown symbol
- **WHEN** EarningsAPI answers an empty array or HTTP 404 for a symbol
- **THEN** the request fails with `DATA_NOT_FOUND`

### Requirement: Day calendar from EarningsAPI
`get_earnings_for_date(day)` SHALL request `GET /v2/calendar/earnings?date=<YYYY-MM-DD>` once and SHALL return one event per entry of `pre`, `after` and `notSupplied` with `report_date` the requested day, `report_time` `bmo`, `amc` and `unknown` respectively, the symbol in canonical form, and all other fields mapped as for per-symbol events. A day whose groups are all empty SHALL be an empty result, not an error. The provider SHALL only send explicit dates, never `today`, `yesterday` or `tomorrow`.

#### Scenario: One request for the whole market
- **WHEN** the day calendar of 2026-11-24 is requested
- **THEN** exactly one request with `date=2026-11-24` is sent and the result contains the events of all three groups

#### Scenario: Group defines release time
- **WHEN** ADI is listed in `pre` and ACCO in `after`
- **THEN** ADI's event has `report_time: "bmo"` and ACCO's `report_time: "amc"`

#### Scenario: Day without reports
- **WHEN** EarningsAPI answers a day with empty `pre`, `after` and `notSupplied`
- **THEN** the result is empty and the day counts as synchronised

### Requirement: EarningsAPI errors and pacing
The provider SHALL space its requests at least 1.0 s apart per process (60 per minute) and SHALL retry HTTP 429 that signals the per-minute limit with bounded retries, honouring `Retry-After`. An HTTP 429 or notice that signals the exhausted daily or monthly quota SHALL be mapped to `PROVIDER_QUOTA_EXHAUSTED` and SHALL set the day counter to its budget. HTTP 401 and 403 SHALL be mapped to `PROVIDER_NOT_AVAILABLE` with a message that the key is invalid. Other non-200 responses SHALL use `map_httpx_http_error`; a response that is not a JSON array SHALL be `PROVIDER_ERROR`. The provider SHALL never return an error as an empty result. Every request SHALL pass the request budget and increment `mdh_provider_upstream_requests_total`.

#### Scenario: Per-minute limit
- **WHEN** EarningsAPI answers HTTP 429 for the per-minute limit with `Retry-After: 2`
- **THEN** the provider waits and retries without exhausting the day counter

#### Scenario: Daily quota used up
- **WHEN** EarningsAPI signals that the daily quota is used up
- **THEN** the request fails with `PROVIDER_QUOTA_EXHAUSTED` and further requests that day are refused locally

#### Scenario: Invalid key
- **WHEN** EarningsAPI answers HTTP 401
- **THEN** the request fails with `PROVIDER_NOT_AVAILABLE`

#### Scenario: Budget refusal
- **WHEN** 100 requests were sent today
- **THEN** no request is sent and the provider raises `PROVIDER_QUOTA_EXHAUSTED` with `period: "day"`

### Requirement: EarningsAPI connection test
`test_connection()` SHALL verify the key with one `GET /v2/earnings?symbol=AAPL` request, report success, status and message like other providers, and count against the budget.

#### Scenario: Valid key
- **WHEN** an admin tests the connection with a valid key
- **THEN** the result is successful and the day counter increases by one
