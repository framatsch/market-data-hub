# earnings-calendar Specification

## Purpose
TBD - created by archiving change add-earnings-calendar. Update Purpose after archive.
## Requirements
### Requirement: Earnings provider capability
The system SHALL define two earnings provider interfaces, each a capability of its own, and a provider SHALL implement one or both:

- `BaseEarningsHistoryProvider` (capability `earnings_history`): `get_earnings_history(root)` returning the reported events of one root, and `test_connection()`.
- `BaseEarningsUpcomingProvider` (capability `earnings_upcoming`): `upcoming_mode` `calendar` with `get_upcoming_earnings(start, end, roots)` returning upcoming events with report dates within `start`…`end` inclusive for the given roots or, when `roots` is `None`, for every symbol the provider covers; or `upcoming_mode` `symbol` with `get_symbol_earnings(root)` returning the upcoming and reported events of one root in one request; optionally `earnings_day_calendar = true` with `get_earnings_for_date(day)` returning the events of all symbols reporting on one day; and `test_connection()`.

Both interfaces SHALL derive from `BaseEarningsProvider`, which keeps the catalog capability `earnings` as the union of both for existing clients. Alpha Vantage SHALL implement both (mode `calendar`), Financial Datasets only `BaseEarningsHistoryProvider`, EarningsAPI both (mode `symbol` with day calendar; its history and per-symbol requests are the same request). The registry SHALL list enabled providers per capability and SHALL resolve each role through its own default (`default_earnings_upcoming_provider`, `default_earnings_history_provider`) or the `provider` query parameter.

#### Scenario: Provider listed per role
- **WHEN** Alpha Vantage and Financial Datasets are enabled and `GET /providers` is called
- **THEN** `available.earnings_upcoming` is `["alphavantage"]`, `available.earnings_history` is `["alphavantage", "financialdatasets"]` and `available.earnings` lists both

#### Scenario: No earnings provider configured
- **WHEN** neither earnings default is configured and `GET /earnings/next?symbols=AAPL` is called without `provider`
- **THEN** the response is HTTP 503 with `detail: "No earnings provider configured — enable a provider in the admin UI"`

#### Scenario: Provider without the capability
- **WHEN** `GET /earnings/calendar?symbols=AAPL&provider=schwab` is called
- **THEN** the response is HTTP 400 `INVALID_PROVIDER` naming `schwab`

#### Scenario: History-only provider asked for upcoming events
- **WHEN** `GET /earnings/next?symbols=AAPL&provider=financialdatasets` is called
- **THEN** the response is HTTP 501 `CAPABILITY_NOT_SUPPORTED`

#### Scenario: Per-symbol provider
- **WHEN** `GET /earnings/next?symbols=ADI&provider=earningsapi` is called
- **THEN** the service never calls `get_upcoming_earnings` of `earningsapi`

### Requirement: Earnings event model
Every earnings event SHALL carry `symbol` (canonical), `report_date`, `report_time` (`bmo`, `amc`, `during` or `unknown`), `date_status` (`confirmed`, `projected` or `unknown`), `reported` (boolean), `provider` and `updated_at`, and MAY carry `fiscal_period_end`, `eps_estimate`, `eps_actual`, `eps_surprise`, `eps_surprise_pct`, `revenue_estimate`, `revenue_actual` and `currency`. Revenue values SHALL be absolute amounts in the event's currency. `date_status` SHALL reflect only what the provider states, except that reported events SHALL be `confirmed`; the system SHALL NOT estimate, extrapolate or default a report date. `reported` SHALL be true when `report_date` is before today in New York or `eps_actual` is present.

#### Scenario: Provider does not state confirmation
- **WHEN** the provider delivers an upcoming event without any confirmation information
- **THEN** the event has `date_status: "unknown"`

#### Scenario: Release time unknown
- **WHEN** the provider delivers no release time
- **THEN** the event has `report_time: "unknown"`

#### Scenario: Past event without actual EPS
- **WHEN** an event lies three days in the past and the provider has no actual EPS yet
- **THEN** the event has `reported: true` and `eps_actual: null`

#### Scenario: Provider without revenue
- **WHEN** Alpha Vantage delivers an event
- **THEN** `revenue_estimate` and `revenue_actual` are `null`

#### Scenario: Revenue in CSV export
- **WHEN** `GET /earnings/calendar?symbols=ADI&provider=earningsapi&format=csv` is requested
- **THEN** each row carries `revenue_estimate` and `revenue_actual` columns

### Requirement: Earnings calendar endpoint
`GET /earnings/calendar` SHALL accept `symbols` (comma-separated, 1–50 after de-duplication), `from`, `to` (dates, defaults today − 30 days and today + 90 days, range at most 800 days), `kind`, `provider` and `format` (`json` or `csv`). It SHALL return the events of all requested stocks in the range, sorted by `report_date` and then `symbol`, and `meta.symbols` with one entry per requested symbol holding `symbol`, `status` (`ok`, `not_applicable`, `not_found` or `error`), `history` (`complete`, `pending` or `not_requested`) and an optional `message`. For upcoming providers in mode `calendar`, upcoming events SHALL come from the provider's calendar, which SHALL be requested for all symbols together, not once per symbol, and past events SHALL come from the per-symbol history. For upcoming providers in mode `symbol`, events SHALL come from the day-calendar window when the provider has one and from the per-symbol request, at most one per symbol and request, following the per-symbol refresh rules.

#### Scenario: Watchlist calendar
- **WHEN** `GET /earnings/calendar?symbols=AAPL,MSFT,SPY&from=2026-11-17&to=2027-02-28` is requested from a calendar provider
- **THEN** the response contains the AAPL and MSFT events in the range sorted by date, `meta.symbols` marks `SPY` as `not_applicable`, and at most one calendar request was sent to the provider

#### Scenario: Watchlist calendar from a per-symbol provider
- **WHEN** `GET /earnings/calendar?symbols=ADI,AAPL,SPY&provider=earningsapi` is requested, the day-calendar window is synchronised and neither stock was synchronised per symbol
- **THEN** exactly two per-symbol requests are sent (ADI and AAPL) and `SPY` is `not_applicable`

#### Scenario: Too many symbols
- **WHEN** 51 distinct symbols are requested
- **THEN** the response is HTTP 422 and no provider is called

#### Scenario: Non-stock symbol type
- **WHEN** `symbols=I:SPX,AAPL` is requested
- **THEN** the response is HTTP 422 naming `I:SPX`

#### Scenario: History budget used up
- **WHEN** a range reaching into the past is requested for 30 symbols without stored history and the budget allows 20 more requests today
- **THEN** history is fetched for the first 20 symbols in request order, the other 10 have `history: "pending"` and, for a calendar provider, their upcoming events, and the response is HTTP 200

#### Scenario: CSV export
- **WHEN** `format=csv` is requested
- **THEN** the response is a CSV attachment with one row per event and the `X-MDH-Data-As-Of` header

### Requirement: Next earnings endpoint
`GET /earnings/next` SHALL accept `symbols` (1–50) and `provider`, SHALL be served by the upcoming role (see role resolution), and SHALL return one row per requested symbol in request order with `symbol`, `event` (the earliest event with `report_date` on or after today in New York, or `null`), `days_until` (calendar days from today in New York, `null` without event), `last_reported` (the latest stored reported event of the symbol from the history provider, or from the upcoming provider when the history provider has none stored, or `null`; never fetched for this field alone), `status` and `message`. For upcoming providers in mode `calendar` it SHALL be answered from the provider's calendar only and SHALL NOT request per-symbol history. For upcoming providers in mode `symbol` it SHALL use the day-calendar window when the provider has one and SHALL request only symbols that are due under the per-symbol refresh rules, at most one request per symbol, in request order within the remaining budget; `last_reported` MAY then come from the same response. `status` SHALL be `ok` with an event, `none_scheduled` when the upcoming events of the symbol were obtained but contain no event on or after today (for example because the company has not announced its date yet), `not_applicable` for ETFs, and `error` when the upcoming events could not be obtained and nothing is stored for the symbol; a symbol skipped because the budget is exhausted SHALL have the message `provider request budget exhausted`. The endpoint SHALL return HTTP 200 unless the upcoming events could not be obtained for any requested stock and nothing is stored, in which case it SHALL return the provider error.

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

#### Scenario: No history requests from a calendar provider
- **WHEN** `GET /earnings/next` is requested for 25 symbols without stored history from a calendar provider
- **THEN** at most one calendar request and no history request is sent to the provider

#### Scenario: Next earnings beyond the window
- **WHEN** today is 2026-11-18, the window is synchronised and does not contain NVDA, NVDA was never synchronised per symbol and `GET /earnings/next?symbols=NVDA&provider=earningsapi` is requested
- **THEN** one per-symbol request for NVDA is sent and its row has the next event and `last_reported` from that response

#### Scenario: Budget exhausted for a per-symbol provider
- **WHEN** the budget allows 1 more request, the window is synchronised and contains neither ADI nor NVDA, nothing is stored for them and `GET /earnings/next?symbols=ADI,NVDA&provider=earningsapi` is requested
- **THEN** ADI is requested and `ok`, NVDA has `status: "error"` with message `provider request budget exhausted`, and the response is HTTP 200

#### Scenario: Provider down without stored calendar
- **WHEN** the calendar request fails and no calendar is stored
- **THEN** the response carries the provider error status code

### Requirement: Company earnings endpoint
`GET /companies/{symbol}/earnings` SHALL return the reported and upcoming events of one stock with `from` and `to` defaulting to today − 1095 days and today + 400 days, sorted by `report_date` ascending, with `kind`, `provider` and `format` like the calendar endpoint. An ETF SHALL be answered with HTTP 422 `CAPABILITY_NOT_SUPPORTED` without a provider call; a symbol for which the provider knows neither history nor upcoming events SHALL be answered with HTTP 404.

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
When the history store is enabled (`DATABASE_URL`), the system SHALL store earnings events per provider, canonical symbol and report date with their source (`calendar` or `history`), and SHALL track per provider the calendar's covered range and synchronisation times, per provider and day the day calendar's synchronisation times, and per provider and symbol the history's synchronisation times. A calendar synchronisation SHALL store the events of every symbol the provider returns and SHALL, in one transaction, replace the provider's `calendar` events in the covered range. A day-calendar synchronisation SHALL, in one transaction, replace all of the provider's events of that day regardless of source, delete for every symbol in the day the provider's unreported events of that symbol dated today or later, within 60 days of the day and not on it, and mark the symbol synchronisation of every symbol whose event on that day disappeared as invalidated. A history synchronisation SHALL insert or update the symbol's events; for an upcoming provider in mode `symbol` it SHALL, in the same transaction, delete the provider's stored events of the symbol dated today or later that are not in the response and clear the symbol's invalidation. Events of different providers SHALL never be mixed.

#### Scenario: Report date moved
- **WHEN** the stored calendar has AAPL on 2027-01-28 and the next calendar synchronisation returns AAPL on 2027-01-30
- **THEN** the store holds only the event on 2027-01-30 for AAPL from that provider

#### Scenario: Report date moved into the window
- **WHEN** EarningsAPI's stored events of ADI contain 2026-12-09 from the per-symbol request and the day calendar of 2026-11-24 lists ADI
- **THEN** the store holds only the upcoming event on 2026-11-24 for ADI from `earningsapi`

#### Scenario: Report date moved out of the window
- **WHEN** the stored day calendar of 2026-11-24 has ADI and its next synchronisation no longer lists ADI
- **THEN** the event is removed and the next earnings request that includes ADI synchronises it per symbol

#### Scenario: Report date moved at a per-symbol request
- **WHEN** EarningsAPI's stored events of ADI contain 2027-02-18 and the next per-symbol synchronisation of ADI returns 2027-02-24 instead
- **THEN** the store holds only the upcoming event on 2027-02-24 for ADI from `earningsapi`

#### Scenario: Calendar covers unrequested symbols
- **WHEN** a calendar synchronisation triggered by a request for AAPL returns events for 4,000 symbols
- **THEN** a later `GET /earnings/next?symbols=NVDA` is answered from the store without a provider call

#### Scenario: Provider isolation
- **WHEN** events of AAPL are stored for two providers
- **THEN** a request with `provider=alphavantage` returns only Alpha Vantage events

### Requirement: Request-driven earnings refresh
For upcoming providers in mode `calendar`, a request SHALL synchronise the calendar only when its last successful synchronisation is older than `EARNINGS_CALENDAR_RESYNC_HOURS` (default 24) or the requested range exceeds its covered range, and SHALL synchronise a symbol's history only when the request needs dates before today and the symbol has no history synchronisation, or when a stored event of the symbol dated within the last `EARNINGS_ACTUALS_WINDOW_DAYS` (default 10) has no `eps_actual` and the history was synchronised more than 12 hours ago. For upcoming providers in mode `symbol`, a request SHALL synchronise a requested stock only when (a) it has no successful synchronisation and the request needs its past, or needs its next event and the day-calendar window holds no event of it on or after today; (b) it has no stored event on or after today and its last successful synchronisation is before the date of its latest stored event (the report has happened since; once per quarter) or older than `EARNINGS_SYMBOL_RESYNC_DAYS` (default 7, only while no date is announced); a stock with a stored event on or after today SHALL NOT be synchronised per symbol for its age alone, because moved dates are caught by the day-calendar window; (c) its synchronisation was invalidated by a day calendar; or (d) the request does not use a day calendar (the provider has none, or the request does not reach into the window, for example `kind=reported` or the history role of a composed response), a stored event of the symbol dated today or within the last `EARNINGS_ACTUALS_WINDOW_DAYS` has no `eps_actual` and the last synchronisation is more than 12 hours ago. After a failed synchronisation the same calendar, day or symbol SHALL NOT be retried for `EARNINGS_RETRY_MINUTES` (default 30).

#### Scenario: Fresh calendar is not refetched
- **WHEN** the calendar was synchronised 3 hours ago
- **THEN** `GET /earnings/next` for any stocks makes no provider call

#### Scenario: Waiting for the actual EPS
- **WHEN** AAPL reported two days ago, its stored event has no `eps_actual` and its history was synchronised 13 hours ago
- **THEN** the next request that includes AAPL's past synchronises AAPL's history

#### Scenario: Retry pause after failure
- **WHEN** a calendar synchronisation failed 10 minutes ago
- **THEN** a request serves the stored calendar and makes no provider call

#### Scenario: Fresh per-symbol data is not refetched
- **WHEN** the window is synchronised, ADI was synchronised from EarningsAPI 3 days ago and has no stored event on or after today
- **THEN** `GET /earnings/next?symbols=ADI&provider=earningsapi` makes no provider call

#### Scenario: Known next date is not refetched
- **WHEN** ADI's stored next event is 2027-02-18, outside the window, and ADI was last synchronised from EarningsAPI 60 days ago
- **THEN** `GET /earnings/next?symbols=ADI&provider=earningsapi` makes no per-symbol request

#### Scenario: Next quarter after the report
- **WHEN** ADI reported on 2026-11-24, has no stored event on or after today and was last synchronised on 2026-11-10
- **THEN** the next earnings request that includes ADI synchronises it once

#### Scenario: Date not announced yet
- **WHEN** ADI has no stored event on or after today and was last synchronised after its latest report 8 days ago
- **THEN** the next earnings request that includes ADI synchronises it; 3 days after a synchronisation it would not

#### Scenario: Reported events after the report
- **WHEN** ADI's stored event of 2026-11-24 came from a per-symbol synchronisation on 2026-11-10 and `GET /companies/ADI/earnings?kind=reported&provider=earningsapi` is requested on 2026-11-26
- **THEN** ADI is synchronised per symbol once and the event of 2026-11-24 carries the reported values, without a day-calendar request

#### Scenario: Next event inside the window
- **WHEN** ADI's next event is in the synchronised window and ADI was last synchronised per symbol 30 days ago
- **THEN** `GET /earnings/next?symbols=ADI&provider=earningsapi` makes no per-symbol request

### Requirement: Earnings without the store
When the history store is disabled or failing open, the system SHALL keep the provider's parsed calendar in Redis for `EARNINGS_CALENDAR_RESYNC_HOURS` and SHALL obtain history per request through the response cache. For upcoming providers in mode `symbol` it SHALL keep each day calendar's parsed result in Redis for 7 days and each symbol's parsed result for `EARNINGS_SYMBOL_RESYNC_DAYS`, each with its synchronisation time, and apply the day-window and per-symbol refresh rules to them without invalidation. Without Redis it SHALL call the provider within its request budget. `meta.stale` SHALL be false in this mode.

#### Scenario: Two watchlists without database
- **WHEN** `DATABASE_URL` is unset and two different `GET /earnings/next` requests arrive within an hour
- **THEN** the provider calendar is requested once

#### Scenario: Per-symbol provider without database
- **WHEN** `DATABASE_URL` is unset and `GET /earnings/next?symbols=NVDA&provider=earningsapi` is requested twice within an hour
- **THEN** each window day and NVDA are requested from EarningsAPI at most once

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
The MCP server SHALL provide `get_earnings_calendar` (arguments `symbols`, optional `from_date`, `to_date`, `kind`, `provider`) and `get_next_earnings` (arguments `symbols`, optional `provider`) returning the same data as the HTTP endpoints through the same service, storage and cache policy.

#### Scenario: Next earnings via MCP
- **WHEN** an MCP client calls `get_next_earnings` with `symbols: ["AAPL", "SPY"]`
- **THEN** the result has one row per symbol with the same fields and statuses as `GET /earnings/next`

#### Scenario: Upcoming events via MCP
- **WHEN** an MCP client calls `get_earnings_calendar` with `symbols: ["ADI"]` and `kind: "upcoming"`
- **THEN** the result contains only events with `reported: false`

### Requirement: Day-calendar window
For upcoming providers that declare a day calendar, the system SHALL keep the weekdays from the previous weekday through `EARNINGS_DAY_CALENDAR_WEEKDAYS` (default 7) weekdays after today (New York) synchronised through `get_earnings_for_date`, one provider request per day. A day SHALL be due when it has no successful synchronisation, or when it is the previous weekday, today or one of the next two weekdays and its last successful synchronisation is older than 20 hours, and it is not paused after a failure for `EARNINGS_RETRY_MINUTES`. A request whose range reaches into the window SHALL synchronise the due days in date order within the request budget before any per-symbol request; `GET /earnings/next` always reaches into the window. Weekend days SHALL NOT be requested. A day calendar SHALL be authoritative for its date for that provider.

#### Scenario: Window filled on first use
- **WHEN** today is Wednesday 2026-11-18, nothing is stored and `GET /earnings/next?symbols=ADI&provider=earningsapi` is requested
- **THEN** the days 2026-11-17 through 2026-11-27 except the weekend are requested once each, in date order

#### Scenario: Steady state
- **WHEN** the window was synchronised completely yesterday
- **THEN** the first request today synchronises the previous weekday, today, the next two weekdays and the new last day of the window, and no other day

#### Scenario: Window answers next earnings
- **WHEN** the window holds ADI on 2026-11-24 and ADI was never synchronised per symbol
- **THEN** `GET /earnings/next?symbols=ADI&provider=earningsapi` returns that event without a per-symbol request

#### Scenario: Actuals from the previous day
- **WHEN** ADI reported before the open on the previous weekday and that day is refreshed today
- **THEN** ADI's event carries `eps_actual` without a per-symbol request

### Requirement: Event kind filter
`GET /earnings/calendar` and `GET /companies/{symbol}/earnings` SHALL accept `kind` with the values `all` (default), `upcoming` and `reported`, and the MCP tool `get_earnings_calendar` an optional argument `kind` with the same values. `upcoming` SHALL return only events with `reported: false`, `reported` only events with `reported: true`. With `kind=upcoming` the system SHALL NOT request per-symbol history from upcoming providers in mode `calendar` and `meta.symbols[].history` SHALL be `not_requested`; with `kind=reported` it SHALL NOT request a calendar or day calendar. An invalid value SHALL be answered with HTTP 422.

#### Scenario: Forward events only
- **WHEN** `GET /earnings/calendar?symbols=AAPL,MSFT&kind=upcoming` is requested from Alpha Vantage
- **THEN** only events with `reported: false` are returned and no history request is sent

#### Scenario: Reported events only
- **WHEN** `GET /companies/ADI/earnings?kind=reported&provider=earningsapi` is requested
- **THEN** only events with `reported: true` are returned and no day calendar is requested

#### Scenario: Invalid kind
- **WHEN** `kind=forward` is requested
- **THEN** the response is HTTP 422 and no provider is called

### Requirement: Earnings roles in the provider catalog
`GET /providers` SHALL list under `available.earnings_upcoming` and `available.earnings_history` the enabled providers implementing the respective interface and under `available.earnings` the union, and SHALL include `defaults.earnings_upcoming`, `defaults.earnings_history` and, for existing clients, `defaults.earnings` equal to `defaults.earnings_upcoming`. When a provider is explicitly asked for a role it does not implement, the `CAPABILITY_NOT_SUPPORTED` error SHALL carry `details.supported` with the enabled providers of that role and a message naming the missing role (for example that the provider only delivers reported earnings).

#### Scenario: Catalog with separate roles
- **WHEN** EarningsAPI and Financial Datasets are enabled, `default_earnings_upcoming_provider` is `earningsapi`, `default_earnings_history_provider` is `financialdatasets` and `GET /providers` is called
- **THEN** `available.earnings_upcoming` is `["earningsapi"]`, `available.earnings_history` is `["earningsapi", "financialdatasets"]`, `defaults.earnings_upcoming` and `defaults.earnings` are `"earningsapi"` and `defaults.earnings_history` is `"financialdatasets"`

#### Scenario: History-only provider asked for next earnings
- **WHEN** EarningsAPI is enabled and `GET /earnings/next?symbols=AAPL&provider=financialdatasets` is called
- **THEN** the response is HTTP 501 `CAPABILITY_NOT_SUPPORTED` with `details.supported: ["earningsapi"]` and a message that `financialdatasets` only delivers reported earnings

### Requirement: Earnings role resolution and composed responses
Without `provider`, `GET /earnings/next` and requests with `kind=upcoming` SHALL use the upcoming default, requests with `kind=reported` the history default, and requests with `kind=all` both: events with `reported: false` SHALL come only from the upcoming provider and events with `reported: true` only from the history provider. When both defaults name the same provider, the response SHALL be served by that provider alone as before. In a composed response an unreported event SHALL be dropped when the history provider has a reported event of the same symbol dated within 7 days of it; every event SHALL keep its own `provider`; `meta.provider` SHALL be the single provider or, for a composed response, `null` with `meta.providers: {"upcoming": …, "history": …}`; `meta.symbols[].history` SHALL describe the history provider. A role without a configured default SHALL contribute no events and its symbols SHALL carry the message `no <role> earnings provider configured`; when no role can be served the request SHALL fail with 503. With `provider`, that provider SHALL serve every requested role it implements; with `kind=all` the roles it lacks SHALL contribute no events, and with `kind=upcoming`, `kind=reported` or `/earnings/next` a missing role SHALL be answered with 501. Each provider's data SHALL be fetched, stored and refreshed under its own name and budget.

#### Scenario: Forward from one provider, history from another
- **WHEN** the upcoming default is `earningsapi`, the history default is `financialdatasets` and `GET /companies/ADI/earnings` is requested
- **THEN** the past events come from Financial Datasets, the upcoming event of 2026-11-24 comes from EarningsAPI, each event names its provider and `meta.providers` names both

#### Scenario: Report day overlap
- **WHEN** in a composed response EarningsAPI still lists ADI on 2026-11-24 as unreported and Financial Datasets has a reported ADI event on 2026-11-24
- **THEN** only the reported Financial Datasets event is returned for that report

#### Scenario: One provider for both roles
- **WHEN** both defaults are `earningsapi` and `GET /companies/ADI/earnings` is requested
- **THEN** all events come from EarningsAPI and `meta.provider` is `"earningsapi"`

#### Scenario: Next earnings use the upcoming role
- **WHEN** the upcoming default is `earningsapi`, the history default is `financialdatasets` and `GET /earnings/next?symbols=ADI` is requested
- **THEN** the event comes from EarningsAPI and no request is sent to Financial Datasets

#### Scenario: Explicit history-only provider with kind all
- **WHEN** `GET /companies/ADI/earnings?provider=financialdatasets` is requested
- **THEN** only reported events from Financial Datasets are returned

