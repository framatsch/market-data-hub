## ADDED Requirements

### Requirement: Alpha Vantage provider registration
The system SHALL provide a provider `alphavantage` that implements the earnings and the price capability. It SHALL be part of the known providers, disabled by default, enabled and configured in the Admin UI like other providers, and SHALL read its credential `api_key` from the encrypted key store. `GET /api/admin/providers` SHALL list its capabilities as `["prices", "earnings"]`.

#### Scenario: Enable with a key
- **WHEN** an admin stores an `api_key` for `alphavantage` and enables the provider
- **THEN** the registry loads it without a restart and lists it under `price` and `earnings`

#### Scenario: Missing key
- **WHEN** the provider is enabled without an `api_key`
- **THEN** requests to it return HTTP 503 `PROVIDER_NOT_AVAILABLE` naming the missing credential

### Requirement: Upcoming earnings from Alpha Vantage
`get_upcoming_earnings` SHALL request `function=EARNINGS_CALENDAR` without a `symbol` parameter and with the smallest `horizon` (`3month`, `6month`, `12month`) that covers the requested end date, parse the CSV columns `symbol`, `reportDate`, `fiscalDateEnding`, `estimate`, `currency` and `timeOfTheDay`, map `timeOfTheDay` `pre-market` to `bmo`, `post-market` to `amc` and an empty or other value to `unknown`, treat an empty `estimate` as `null`, set `date_status` to `unknown`, drop preferred-share rows (symbols with a `-P` suffix, e.g. `JPM-PD`), keep share classes in dot notation (`BF.B`, `LEN.B`) as canonical symbols, and filter by `roots` and the date range locally.

#### Scenario: One request for many symbols
- **WHEN** upcoming events for 25 roots within the next 60 days are requested
- **THEN** exactly one `EARNINGS_CALENDAR` request with `horizon=3month` is sent

#### Scenario: Long range
- **WHEN** upcoming events up to 200 days ahead are requested
- **THEN** the request uses `horizon=12month`

#### Scenario: Release time mapping
- **WHEN** a calendar row has an empty `timeOfTheDay`
- **THEN** the event has `report_time: "unknown"`

#### Scenario: Preferred shares
- **WHEN** the calendar contains `JPM-PD`
- **THEN** no event for `JPM-PD` is returned

### Requirement: Earnings history from Alpha Vantage
`get_earnings_history` SHALL request `function=EARNINGS&symbol=<root>` and map each entry of `quarterlyEarnings` to a reported event: `reportedDate` to `report_date`, `fiscalDateEnding` to `fiscal_period_end`, `reportedEPS`, `estimatedEPS`, `surprise` and `surprisePercentage` to the EPS fields (the string `None` or an empty value as `null`), `reportTime` `pre-market`/`post-market` to `bmo`/`amc` and other values to `unknown`, and `date_status` `confirmed`. Share classes SHALL be sent in dash notation (`BRK.B` → `BRK-B`). An empty JSON object, which Alpha Vantage returns for unknown symbols and ETFs, SHALL be `DATA_NOT_FOUND`.

#### Scenario: Quarterly history
- **WHEN** the history of AAPL is requested
- **THEN** each quarter becomes one event with `reported: true`, its estimate, actual, surprise and release time

#### Scenario: Missing estimate
- **WHEN** a quarter has `estimatedEPS: "None"`
- **THEN** the event has `eps_estimate: null` and the other fields are kept

#### Scenario: Share class
- **WHEN** the history of `BRK.B` is requested
- **THEN** Alpha Vantage is queried with `BRK-B` and the events carry `symbol: "BRK.B"`

#### Scenario: Unknown symbol
- **WHEN** Alpha Vantage answers `{}`
- **THEN** the request fails with `DATA_NOT_FOUND`

### Requirement: Prices from Alpha Vantage
The provider SHALL declare `price_sec_types` and `price_history_sec_types` `{stock, etf}` and `native_intervals` `{1d, 1w}`. Daily bars SHALL come from `function=TIME_SERIES_DAILY` with the default (compact) output size, which delivers the latest 100 trading days; weekly bars from `function=TIME_SERIES_WEEKLY`, which delivers the full history. Bars outside the requested range SHALL be dropped; a range that starts before the first delivered daily bar SHALL return the delivered bars without error. Bar timestamps SHALL be the trading date in `America/New_York`; a weekly row is dated with the week's last trading day and SHALL be mapped to the canonical week bucket. `get_last_price` SHALL use `function=GLOBAL_QUOTE` and SHALL set the quote time to the close (16:00 New York) of `latest trading day`, so that clients see the quote is end-of-day. Share classes SHALL use dash notation. Intraday intervals SHALL NOT be declared; requests for them are answered by the existing unsupported-interval rules.

#### Scenario: Recent daily bars
- **WHEN** `GET /prices/AAPL/history?interval=1d&provider=alphavantage` is requested for the last 30 days
- **THEN** one `TIME_SERIES_DAILY` request is sent and the bars of the range are returned

#### Scenario: Range beyond the compact window
- **WHEN** daily bars for the last 400 days are requested
- **THEN** the response contains the latest 100 trading days and no error

#### Scenario: Weekly history
- **WHEN** weekly bars since 2010 are requested
- **THEN** one `TIME_SERIES_WEEKLY` request returns them

#### Scenario: Intraday
- **WHEN** `interval=1h` is requested from Alpha Vantage
- **THEN** the response is the unsupported-interval error without a provider call

#### Scenario: End-of-day quote
- **WHEN** `GET /prices/AAPL/last?provider=alphavantage` is requested during the session
- **THEN** the quote has the previous close and its timestamp is the close of `latest trading day`

### Requirement: Unadjusted Alpha Vantage bars
The provider SHALL document that its free-tier bars are not adjusted for splits or dividends (`TIME_SERIES_DAILY_ADJUSTED` is premium), and the admin provider details SHALL show `price_adjustment: "none"` for it. The system SHALL NOT adjust the bars itself.

#### Scenario: Split in weekly history
- **WHEN** weekly AAPL bars across 28 August 2020 are requested
- **THEN** the closes jump from about 499 to about 121 as delivered by Alpha Vantage

### Requirement: Alpha Vantage notices and errors
A response with HTTP 200 that contains an `Information` or `Note` field explicitly reporting daily-quota exhaustion SHALL be mapped to `PROVIDER_QUOTA_EXHAUSTED` and SHALL set the provider's day counter to its budget. Per-second or burst throttles SHALL be classified first, even when their text also mentions daily limits or premium endpoints; they SHALL use request pacing and bounded retry and SHALL NOT exhaust the day counter. A notice specifically denying a premium endpoint or premium feature SHALL be mapped to `PROVIDER_NOT_ENTITLED`; an `Error Message` field SHALL be mapped to `DATA_NOT_FOUND` for symbol requests and to `PROVIDER_ERROR` otherwise. An invalid key SHALL be mapped to `PROVIDER_NOT_AVAILABLE`. Non-200 responses SHALL use the shared mapping `map_httpx_http_error`. The provider SHALL never return such a notice as an empty result.

#### Scenario: Daily limit notice
- **WHEN** Alpha Vantage answers HTTP 200 with an `Information` text about the daily request limit
- **THEN** the request fails with `PROVIDER_QUOTA_EXHAUSTED` and further requests that day are refused locally

#### Scenario: Premium notice
- **WHEN** Alpha Vantage answers "This is a premium endpoint"
- **THEN** the request fails with `PROVIDER_NOT_ENTITLED`

#### Scenario: Burst notice also mentions the daily limit
- **WHEN** Alpha Vantage asks for "1 request per second" and also mentions "25 requests per day" and premium endpoints
- **THEN** the provider handles a temporary burst throttle with bounded retry, without exhausting the day counter or reporting missing entitlement

### Requirement: Alpha Vantage connection test
`test_connection()` SHALL verify the key with one `GLOBAL_QUOTE` request, report success, status and message like other providers, and count against the budget.

#### Scenario: Valid key
- **WHEN** an admin tests the connection with a valid key
- **THEN** the result is successful and the day counter increases by one

### Requirement: Request budgets for metered providers
The system SHALL provide a request budget usable by any provider, configured by the connection settings `request_budget_per_day` and `request_budget_per_month` (integers ≥ 0, `0` = no limit) and editable in the provider details. Alpha Vantage SHALL default to 25 per day and no monthly limit. One budget SHALL cover all capabilities of a provider. Before every upstream request the budget SHALL increment counters for the current day (`America/New_York`) and month (UTC) shared across replicas through Redis, falling back to process-local counters when Redis is unavailable, and SHALL raise the new error code `PROVIDER_QUOTA_EXHAUSTED` (HTTP 429, details `provider`, `period`, `budget`) without sending the request when a counter would exceed its budget. It SHALL log one warning per period when 80 % of a budget is used. `GET /api/admin/providers/{name}/usage` SHALL require admin authentication and return per period `used`, `budget` and `resets_at`, and `shared` (false when the local fallback counter is in use); the Admin UI SHALL show it in the provider details of metered providers.

#### Scenario: Daily budget reached
- **WHEN** 25 Alpha Vantage requests were sent today and a history request is due
- **THEN** no request is sent and the provider raises `PROVIDER_QUOTA_EXHAUSTED` with `period: "day"`

#### Scenario: Prices and earnings share the budget
- **WHEN** 20 price requests and 5 earnings requests were sent today
- **THEN** the next request of either capability is refused

#### Scenario: New day
- **WHEN** the day in New York changes
- **THEN** the day counter starts at 0

#### Scenario: No limit
- **WHEN** both budgets are 0
- **THEN** requests are counted but never refused

#### Scenario: Invalid budget
- **WHEN** an admin sets `request_budget_per_day` to -1
- **THEN** the provider configuration endpoint responds with 422

### Requirement: Upstream request metric
Every request sent to a metered provider SHALL increment the Prometheus counter `mdh_provider_upstream_requests_total` with the provider's name as label.

#### Scenario: Counted request
- **WHEN** one `EARNINGS_CALENDAR` request is sent
- **THEN** the counter for `alphavantage` increases by one
