## ADDED Requirements

### Requirement: Financial Datasets provider registration
The system SHALL provide a provider `financialdatasets` that implements the earnings capability (history only), the price capability and the company capability. It SHALL be part of the known providers, disabled by default, enabled and configured in the Admin UI like other providers, and SHALL send its credential `api_key` from the encrypted key store as header `X-API-KEY` to `https://api.financialdatasets.ai`. `GET /api/admin/providers` SHALL list its capabilities as `["prices", "companies", "earnings"]`. Its request budget (see `alphavantage-provider`) SHALL default to 0 per day and 1000 per month, which is USD 20 at USD 0.02 per request.

#### Scenario: Enable with a key
- **WHEN** an admin stores an `api_key` for `financialdatasets` and enables the provider
- **THEN** the registry loads it without a restart and lists it under `price`, `company` and `earnings`

#### Scenario: Missing credit or key
- **WHEN** Financial Datasets answers HTTP 402 `Payment required`
- **THEN** the request fails with `PROVIDER_NOT_AVAILABLE` and a message that the key is missing or the credit is used up

### Requirement: Earnings history from Financial Datasets
The provider SHALL declare that it does not deliver upcoming earnings (`earnings_upcoming = False`). `get_earnings_history` SHALL request `GET /earnings?ticker=<root>` with a `limit` covering the requested history and follow `next_page_url`. For each `report_period` it SHALL use the earliest filing with `source_type` `8-K` as the report, or the earliest filing of the period when there is no 8-K: `filing_date` as `report_date`, `report_period` as `fiscal_period_end`, `quarterly.earnings_per_share` as `eps_actual` and `currency`. `report_time` SHALL follow `filing_window` (enum of the published OpenAPI schema): `PRE_MARKET` → `bmo`, `DURING_MARKET` → `during`, `AFTER_HOURS` → `amc` when `filing_datetime` is at or after 16:00 Eastern Time and `bmo` when it is before 04:00, `WEEKEND` or `null` → `unknown`. `eps_estimate` and the surprise fields SHALL be `null`; `date_status` SHALL be `confirmed`.

#### Scenario: Report time from the SEC filing
- **WHEN** the earliest 8-K of a quarter was accepted by the SEC at 16:31 Eastern Time with `filing_window: "AFTER_HOURS"`
- **THEN** the event has `report_time: "amc"` and `report_date` the filing date

#### Scenario: Early-morning filing
- **WHEN** the 8-K was accepted at 03:45 Eastern Time with `filing_window: "AFTER_HOURS"`
- **THEN** the event has `report_time: "bmo"`

#### Scenario: 10-Q without 8-K
- **WHEN** a period has only a 10-Q filing
- **THEN** that filing's date and window are used

#### Scenario: No estimates
- **WHEN** the history of AAPL is requested from Financial Datasets
- **THEN** every event has `eps_estimate: null` and `eps_surprise_pct: null`

### Requirement: Providers without upcoming earnings
A provider that declares `earnings_upcoming = False` SHALL NOT be asked for upcoming earnings. `GET /earnings/next` with such a provider SHALL be answered with HTTP 501 `CAPABILITY_NOT_SUPPORTED`; the calendar and company earnings endpoints SHALL return its reported events only.

#### Scenario: Next earnings from a history-only provider
- **WHEN** `GET /earnings/next?symbols=AAPL&provider=financialdatasets` is requested
- **THEN** the response is HTTP 501 `CAPABILITY_NOT_SUPPORTED` without a provider call

### Requirement: Prices from Financial Datasets
The provider SHALL declare `price_sec_types` and `price_history_sec_types` `{stock, etf}` and `native_intervals` `{1d, 1w}`; a ticker the provider does not cover answers 404 and SHALL be `DATA_NOT_FOUND`. Historical bars SHALL come from `GET /prices` with `interval` `day` or `week`, `start_date` and `end_date`, following `next_page_url`; `time` (UTC) SHALL be mapped to the trading date in `America/New_York`. `get_last_price` SHALL use `GET /prices/snapshot` (`price`, `day_change`, `time_milliseconds` as quote time). The published schema does not state whether bars are adjusted, so the admin provider details SHALL show `price_adjustment: "unknown"`.

#### Scenario: Daily history in one request
- **WHEN** 620 days of daily AAPL bars are requested
- **THEN** the provider requests `/prices` with `interval=day` for the range and returns all bars, following pagination

### Requirement: Company profile from Financial Datasets
`get_company_profile` SHALL map `GET /company/facts` (`name`, `exchange`, `sector`, `industry`) to `CompanyProfile`. Company search SHALL NOT be offered and SHALL be answered with HTTP 501 `CAPABILITY_NOT_SUPPORTED`.

#### Scenario: Profile
- **WHEN** `GET /companies/AAPL?provider=financialdatasets` is requested
- **THEN** the profile has the name, exchange, sector and industry from the company facts

### Requirement: Financial Datasets errors
HTTP 401 and 402 SHALL map to `PROVIDER_NOT_AVAILABLE` with the `message` of the error body; 404 or an empty result for a ticker SHALL be `DATA_NOT_FOUND`; other HTTP errors SHALL use the shared mapping `map_httpx_http_error`. Every request SHALL pass through the provider's request budget.

#### Scenario: Unknown ticker
- **WHEN** Financial Datasets answers 404 for a ticker
- **THEN** the request fails with `DATA_NOT_FOUND`

### Requirement: Implementation against the published schema
The provider SHALL be implemented and tested against a pinned copy of the published OpenAPI document (`https://www.financialdatasets.ai/openapi.json`) stored with the test fixtures. Test fixtures SHALL be schema-conformant responses, and a contract test SHALL validate every fixture and every request the provider builds (path, query parameters, header) against the pinned document. Updating the pinned copy SHALL make the contract test show schema changes.

#### Scenario: Schema drift
- **WHEN** the pinned OpenAPI copy is replaced by a version in which `filing_window` has a new value
- **THEN** the contract test fails and names the changed enum
