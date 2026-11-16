## ADDED Requirements

### Requirement: Optional history store configuration
The system SHALL support a PostgreSQL history store configured by `DATABASE_URL`. When `DATABASE_URL` is unset or empty the store SHALL be disabled, no database connection SHALL be opened, and every endpoint SHALL behave as without this capability. Credentials, provider configuration and system settings SHALL remain in the SQLite file at `KEYS_DB_PATH` whether or not `DATABASE_URL` is set. The settings `HISTORY_STORE_RESYNC_SECONDS` (default 300, minimum 0), `HISTORY_STORE_OVERLAP_BARS` (default 5, 2–30) and `HISTORY_STORE_MIGRATE_ON_STARTUP` (default `true`) SHALL be read from the environment. The connection pool SHALL be opened in the application lifespan and closed on shutdown. Log output and the admin status SHALL show the database URL without credentials.

#### Scenario: Store disabled
- **WHEN** MDH starts without `DATABASE_URL`
- **THEN** the startup log states that the history store is disabled, and `GET /prices/AAPL/history?interval=1d` calls the provider for the whole requested range

#### Scenario: Empty value
- **WHEN** MDH starts with `DATABASE_URL` set to an empty string
- **THEN** the store is disabled exactly as with an unset variable

#### Scenario: Database configured
- **WHEN** MDH starts with a reachable `DATABASE_URL`
- **THEN** the startup log states that the history store is connected and shows the URL without user name and password

#### Scenario: Database configured but unreachable at startup
- **WHEN** MDH starts with a `DATABASE_URL` whose server does not answer
- **THEN** MDH starts, reports the store as unavailable and serves history from the provider

#### Scenario: Settings and credentials unaffected
- **WHEN** MDH starts with or without `DATABASE_URL`
- **THEN** provider credentials, provider configuration and system settings are read from and written to the SQLite file as before

### Requirement: Schema migration at startup
With `HISTORY_STORE_MIGRATE_ON_STARTUP=true` the system SHALL apply all pending schema migrations before serving requests, holding a PostgreSQL advisory lock so that replicas starting at the same time migrate once. With `false` it SHALL NOT change the schema and SHALL treat a missing or outdated schema as an unavailable store.

#### Scenario: Two replicas start together
- **WHEN** two replicas start at the same time against an empty database
- **THEN** one applies the migrations, the other waits and finds the schema current, and both report the store as connected

#### Scenario: Migration switched off with an empty database
- **WHEN** MDH starts with `HISTORY_STORE_MIGRATE_ON_STARTUP=false` against a database without the schema
- **THEN** MDH starts, reports the store as unavailable and serves history from the provider

### Requirement: Fail-open on database errors
A database error SHALL NOT fail a market data request. On an error the system SHALL log one warning, skip the store for 30 seconds, and answer the request from the provider as with a disabled store. After the cooldown the next request SHALL try the database again, and a success SHALL be logged once.

#### Scenario: Database goes down
- **WHEN** the database becomes unreachable and `GET /prices/AAPL/history?interval=1d` is requested
- **THEN** the response is `200` with bars loaded from the provider, and one warning is logged

#### Scenario: Database comes back
- **WHEN** the database is reachable again after the cooldown
- **THEN** the next request uses the store and one recovery message is logged

### Requirement: Stored intervals per provider
The intervals `1h`, `4h`, `1d` and `1w` are storable. Every price provider SHALL have the setting `history_store_intervals` in its provider configuration: the list of storable intervals whose bars the store keeps for that provider. The default SHALL be `["1d"]`. An empty list SHALL switch price storage off for that provider. The setting SHALL be kept with the other provider configuration, SHALL be editable through the admin provider configuration API and in the provider details of the Admin UI, and SHALL take effect without a restart. A value outside the storable set SHALL be rejected with 422.

A price history request SHALL use the store only when the store is enabled and the requested interval is in the list of the effective provider. Every other price history request SHALL be answered from the provider as without the store. Removing an interval from the list SHALL stop reading and writing its series and SHALL NOT delete stored rows. The setting SHALL NOT affect IV series.

The store SHALL keep the bars the price service returns for an interval and SHALL NOT make an interval available: when the price service fails for a listed interval because the provider does not deliver it, the error SHALL be returned unchanged and nothing SHALL be stored.

#### Scenario: Default
- **WHEN** the store is enabled and no provider configuration was changed
- **THEN** `interval=1d` uses the store for every price provider and `interval=1h`, `4h` and `1w` do not

#### Scenario: Hourly bars switched on for one provider
- **WHEN** an admin sets `history_store_intervals` of `ibkr` to `["1h", "1d"]`
- **THEN** the next `GET /prices/AAPL/history?interval=1h&provider=ibkr` uses the store without a restart, and the same request with `provider=schwab` does not

#### Scenario: Interval removed
- **WHEN** `1h` is removed from the list of `ibkr` while an hourly series of `AAPL` is stored
- **THEN** hourly requests to `ibkr` are answered from the provider, the stored rows remain, and the admin status still counts them

#### Scenario: Storage switched off for a provider
- **WHEN** `history_store_intervals` of `prixe` is an empty list
- **THEN** no price history request to `prixe` reads or writes the store

#### Scenario: Invalid value
- **WHEN** an admin sends `history_store_intervals` `["5m"]`
- **THEN** the response is 422 and the setting is unchanged

#### Scenario: Interval the provider does not deliver
- **WHEN** `1h` is in the list of a provider that has no hourly bars and `interval=1h` is requested from it
- **THEN** the response is the same error as without the store and no series is created

### Requirement: Provider-isolated series
Stored data SHALL be organised in series. A price series SHALL be identified by canonical symbol, effective provider, interval and, for `1h` and `4h`, the `extended_hours` flag of the request. An IV series SHALL be identified by canonical symbol, effective provider, tenor in days and the `ric` instrument override (empty when none). The effective provider is the explicit `provider` parameter or, without one, the configured default for that capability. Data of one series SHALL NOT be returned for another, with the single exception defined in "Stored bars of another provider". Rows of different series SHALL never be combined in one response.

#### Scenario: Two providers
- **WHEN** `GET /prices/SPY/history?interval=1d&provider=schwab` and the same request with `provider=ibkr` are served
- **THEN** each is answered from its own series and every returned bar carries the requested provider

#### Scenario: Default provider changed
- **WHEN** the default price provider is changed from `schwab` to `ibkr` and `GET /prices/SPY/history?interval=1d` is requested without `provider`
- **THEN** no bar stored for `schwab` is returned

#### Scenario: Intervals are separate
- **WHEN** a daily and an hourly series of `SPY` are stored for `ibkr`
- **THEN** `interval=1d` returns only daily bars and `interval=1h` only hourly bars

#### Scenario: Extended hours are separate
- **WHEN** `interval=1h` is requested once without and once with `extended_hours=true`
- **THEN** the two requests use different series, and the first never returns a bar outside the regular session

#### Scenario: Instrument override
- **WHEN** `GET /volatility/DAX/history?ric=GDAXATMIV.EX` and `GET /volatility/DAX/history` are served
- **THEN** they use different series

### Requirement: Only closed bars are stored
The store SHALL hold only closed bars and IV points. A day is closed when it lies before the current session date in `America/New_York`, or is the current session date and the market is settled according to the US market session model of `response-caching` (session end plus 30 minutes grace).
- A `1d` bar and an IV point SHALL be closed when their trading date is a closed day. The trading date of a daily bar SHALL be the UTC calendar date of its start.
- A `1w` bar SHALL be closed when the Friday of its ISO week is a closed day.
- A `1h` or `4h` bar SHALL be closed when the period that contains its start has ended. Periods SHALL be aligned to the clock in `America/New_York`, counted from midnight. For a series without extended hours no period SHALL count as open while the market is settled.

A bar or IV point that is not closed SHALL NOT be written to the store.

#### Scenario: Forming bar during the session
- **WHEN** daily history is requested on Wednesday 11:00 ET and the provider returns a bar for Wednesday
- **THEN** the response contains Wednesday's bar and the store contains no row for Wednesday

#### Scenario: After the settle grace
- **WHEN** daily history is requested on Wednesday 16:45 ET
- **THEN** Wednesday's bar is written to the store

#### Scenario: Weekend
- **WHEN** daily history is requested on Saturday
- **THEN** Friday is the newest closed day and its bar is stored

#### Scenario: Daily bar stamped at UTC midnight
- **WHEN** a provider returns a daily bar with `start` 2026-11-10T00:00:00Z
- **THEN** it is stored as the bar of 10 November, not of 9 November

#### Scenario: Forming hourly bar
- **WHEN** hourly history is requested at 11:20 ET
- **THEN** the response contains the bar that started at 11:00 ET, the store contains the bars up to the one that started at 10:00 ET, and no row for 11:00 ET

#### Scenario: Running week
- **WHEN** weekly history is requested on Wednesday
- **THEN** the response contains the bar of the current week and the store contains no row for it

#### Scenario: Week closed
- **WHEN** weekly history is requested on Friday 16:45 ET
- **THEN** the bar of that week is written to the store

#### Scenario: Evening without extended hours
- **WHEN** an hourly series without extended hours is covered through the session end and hourly history is requested at 19:00 ET
- **THEN** the provider is not called

### Requirement: Price history from the store
For an interval that is stored for the effective provider, `GET /prices/{symbol}/history` and the MCP tool for historical prices SHALL return the closed bars of the requested range from the store and SHALL call the provider only for ranges the series does not cover. For `1d`, `start` and `end` SHALL select bars by trading date, inclusive on both ends. For `1w`, `start` SHALL be moved back to the Monday of its UTC calendar week, and bars SHALL be selected by the UTC calendar date of their start, inclusive on both ends. For `1h` and `4h`, bars SHALL be selected by their start instant, inclusive on both ends. The response SHALL contain the same fields and values per bar as a response built from the provider alone (`symbol`, `start`, `end`, `open`, `high`, `low`, `close`, `volume`, `provider`, `source_instrument`), sorted ascending. Intervals outside the storable set SHALL NOT use the store.

#### Scenario: First request for a series
- **WHEN** `GET /prices/AAPL/history?interval=1d&start=2025-03-06` is requested and no series exists
- **THEN** the provider is called once for the whole range, the closed days are stored, and the response contains all returned bars

#### Scenario: Repeated request while the market is settled
- **WHEN** the same request is repeated on Saturday after a first request on Saturday, and the response cache entry has been removed
- **THEN** the response is identical and the provider is not called

#### Scenario: Request during the session
- **WHEN** the series is covered through Tuesday and the request is made on Wednesday 11:00 ET
- **THEN** the provider is called for a range that starts at most `HISTORY_STORE_OVERLAP_BARS` stored bars before Wednesday, and the response contains the stored bars plus Wednesday's forming bar

#### Scenario: Narrower range
- **WHEN** a series covers 620 days and a request asks for the last 30 days while the market is settled
- **THEN** the 30 days are returned without a provider call

#### Scenario: Hourly history from the store
- **WHEN** `1h` is stored for `ibkr`, an hourly series of `AAPL` covers the last 30 days, and the last 5 days are requested while the market is settled
- **THEN** the bars are returned without a provider call

#### Scenario: Weekly request starting mid-week
- **WHEN** `1w` is stored for the provider and `interval=1w` is requested with `start` Wednesday 2026-11-04
- **THEN** the first returned bar is the bar of the week of Monday 2026-11-02

#### Scenario: Interval below one hour
- **WHEN** `GET /prices/AAPL/history?interval=5m` is requested
- **THEN** the store is neither read nor written

### Requirement: Coverage tracking
Each series SHALL record the earliest point it has loaded (`covered_from`), the newest point it knows (`covered_to`) and the time of its last successful provider call (`synced_at`). The points SHALL be dates for `1d`, `1w` and IV series and instants for `1h` and `4h` series. A day or period inside the covered range without a row SHALL be treated as one without data and SHALL NOT cause a provider call. A request that starts before `covered_from` SHALL load only the missing earlier range and extend the coverage. For a `1h` or `4h` series `covered_from` SHALL be the start of the oldest bar the provider returned, not the requested `start`; a repeated request for an earlier `start` SHALL be subject to the same interval as the tail. For a price series `covered_to` SHALL be set to the newest closed bar period after a successful synchronisation. For an IV series `covered_to` SHALL be the date of the newest stored point.

#### Scenario: Holiday inside the range
- **WHEN** a series covers 1 to 30 November and the provider returned no bar for the 26th
- **THEN** a request for that range returns the bars without the 26th and does not call the provider for it

#### Scenario: Earlier start
- **WHEN** a series covers from 2025-03-06 and a request asks for `start=2024-01-02`
- **THEN** the provider is called for the range from 2024-01-02 up to the start of the stored range, and afterwards the series covers from 2024-01-02

#### Scenario: Provider lookback shorter than the request
- **WHEN** two years of hourly history are requested and the provider returns bars for the last 180 days only
- **THEN** `covered_from` is the start of the oldest returned bar, and the earlier range is not recorded as covered

#### Scenario: Stored bars outlive the provider's lookback
- **WHEN** an hourly series holds bars from 400 days ago and the provider now delivers only the last 180 days
- **THEN** a request for the last 300 days returns the stored bars for the whole range

#### Scenario: IV point not yet published
- **WHEN** an IV series is synchronised on Thursday 17:00 ET and the provider's newest point is Wednesday
- **THEN** `covered_to` is Wednesday and the tail remains due

### Requirement: Throttled tail synchronisation
The tail of a series is due when `covered_to` lies before the newest closed bar period of its interval, or when the request includes a period that is not closed. A due tail SHALL be loaded from the provider only when the last attempt for the series, successful or failed, is older than `HISTORY_STORE_RESYNC_SECONDS`; otherwise the request SHALL be answered from the store. A request carrying `Cache-Control: no-cache` SHALL ignore this interval. Concurrent requests for the same series SHALL share one provider call.

#### Scenario: Two requests within the interval
- **WHEN** two requests for the same daily series with different `start` dates arrive 60 seconds apart during the session with the default interval of 300 seconds
- **THEN** the provider is called once

#### Scenario: Forced refresh
- **WHEN** a request carries `Cache-Control: no-cache` 60 seconds after a synchronisation
- **THEN** the tail is loaded from the provider again

#### Scenario: Parallel requests
- **WHEN** ten requests for the same series arrive at the same time and the tail is due
- **THEN** the provider is called once and all ten receive the same bars

### Requirement: Revision detection
Every tail synchronisation SHALL load the `HISTORY_STORE_OVERLAP_BARS` newest stored bars or points again and compare `open`, `high`, `low` and `close` (for IV: `iv_call`, `iv_put` and `iv`) with the stored values. A difference only in the newest stored bar SHALL overwrite that row. A difference in an older bar SHALL reload the covered range of the series from the provider and replace its rows in one transaction. A difference in `volume` alone SHALL update the row and SHALL NOT cause a reload.

#### Scenario: Stock split
- **WHEN** a series holds closes around 400 and the provider now returns closes around 100 for the overlapped bars after a 4-for-1 split
- **THEN** the whole covered range is loaded again and every stored bar of the series shows the adjusted prices

#### Scenario: Stock split in a weekly series
- **WHEN** a weekly series is synchronised after a split and the four older of the five overlapped weekly bars differ
- **THEN** the series is reloaded

#### Scenario: Reload of an hourly series beyond the provider's lookback
- **WHEN** an hourly series holds bars from 400 days ago, a revision is detected, and the provider delivers only the last 180 days
- **THEN** the series holds the 180 days with the revised prices, and `covered_from` is the start of the oldest returned bar

#### Scenario: Corrected last session
- **WHEN** only the newest stored day differs in `close`
- **THEN** that row is overwritten and no other row is loaded again

#### Scenario: Final volume
- **WHEN** an overlapped day differs only in `volume`
- **THEN** the row is updated and no reload happens

#### Scenario: Reload fails halfway
- **WHEN** the provider fails during a reload
- **THEN** the stored rows of the series are unchanged

### Requirement: Daily IV history from the store
With the store enabled, `GET /volatility/{symbol}/history` and the MCP tool for IV history SHALL return closed days from the store under the same coverage, tail and revision rules as daily prices. Points without any IV value SHALL NOT be stored. The response SHALL equal a response built from the provider alone for the same points.

#### Scenario: Repeated IV history
- **WHEN** `GET /volatility/AAPL/history?provider=lseg` is requested twice on a Saturday and the response cache entry has been removed in between
- **THEN** the second response is identical and the provider is not called

#### Scenario: Tenors are separate
- **WHEN** history for `tenor_days=30` is stored and `tenor_days=60` is requested
- **THEN** the provider is called for the 60-day tenor and the 30-day points are not returned

### Requirement: Stored data on provider failure
When a provider call for a series fails with a connection error, timeout, rate limit or paused provider, and the series covers the closed bars of the requested range, the system SHALL answer `200` with the stored data and set `meta.stale` to `true` and `meta.stale_reason` to the error code. The failure SHALL be recorded as an attempt for the tail interval. When the series does not cover the range, the provider error SHALL be returned unchanged. Entitlement errors (`PROVIDER_NOT_ENTITLED`) and unsupported capabilities (501) SHALL always be returned as errors.

#### Scenario: Provider times out with a covered range
- **WHEN** a price series covers the requested closed days and the tail request to the provider times out during the session
- **THEN** the response is `200` with the stored bars, without a bar for the current day, with `meta.stale` `true` and `meta.stale_reason` `PROVIDER_TIMEOUT`

#### Scenario: Provider down, nothing stored
- **WHEN** no series exists and the provider is unreachable
- **THEN** the response is the provider error with its usual status code

#### Scenario: Outage does not slow every request
- **WHEN** the provider is unreachable and five requests for the same series arrive within the tail interval
- **THEN** the provider is tried once and the other four are answered from the store immediately

#### Scenario: Not entitled
- **WHEN** the provider answers that the subscription does not cover the instrument
- **THEN** the response is `403 PROVIDER_NOT_ENTITLED` even if stored bars exist

### Requirement: Stored bars of another provider
For daily price history only: when the call to the requested provider fails with a connection error, timeout, rate limit or paused provider, its own series does not cover the closed days of the requested range, and a price series of another provider for the same canonical symbol does, the system SHALL answer `200` with the bars of that other series. Every returned bar SHALL carry the provider it was loaded from, and the response SHALL carry `meta.stale` `true`, `meta.stale_reason` and `meta.source_provider`. When several providers qualify, the series with the newest `synced_at` SHALL be used. The requested provider's own series SHALL always take precedence when it covers the range. Nothing SHALL be written to the requested provider's series. Price series of `1h`, `4h` and `1w` and IV history and IV statistics SHALL never be served from a series of another provider.

#### Scenario: Requested provider down, another provider has the bars
- **WHEN** `GET /prices/AAPL/history?interval=1d&provider=ibkr` is requested, IBKR cannot be reached, no IBKR series exists for `AAPL`, and a Schwab series covers the range
- **THEN** the response is `200` with the Schwab bars, each with `provider` `schwab`, and `meta.stale` `true`, `meta.stale_reason` `PROVIDER_CONNECTION_ERROR` and `meta.source_provider` `schwab`

#### Scenario: Own series wins
- **WHEN** the requested provider fails and both its own series and another provider's series cover the range
- **THEN** the bars of the requested provider are returned and `meta.source_provider` is absent

#### Scenario: Provider recovers
- **WHEN** the requested provider answers again on the next request
- **THEN** the response contains its bars, without `meta.stale`, and its series is created from that answer

#### Scenario: Hourly bars are not substituted
- **WHEN** `GET /prices/AAPL/history?interval=1h&provider=ibkr` is requested, IBKR cannot be reached, no IBKR series exists, and a Polygon hourly series covers the range
- **THEN** the provider error is returned

#### Scenario: IV is not substituted
- **WHEN** `GET /volatility/AAPL/stats?provider=ibkr` is requested, IBKR cannot be reached, no IBKR series exists, and an LSEG IV series covers the window
- **THEN** the provider error is returned

### Requirement: Admin history store status endpoint
`GET /api/admin/history-store` SHALL require admin authentication and return `state` (`disabled` | `connected` | `unavailable`), the database URL without credentials, the effective settings, and per dataset (`prices`, `iv`) the number of series, the number of rows, the oldest and newest stored date and the newest `synced_at`. For `prices` the same figures SHALL also be given per interval.

#### Scenario: Connected store
- **WHEN** an admin requests the status with two price series holding 1240 bars
- **THEN** the response shows `state` `connected` and for `prices` 2 series and 1240 rows

#### Scenario: Disabled store
- **WHEN** `DATABASE_URL` is unset
- **THEN** the response shows `state` `disabled` and no counts

#### Scenario: Unavailable store
- **WHEN** `DATABASE_URL` is set and the database cannot be reached
- **THEN** the response is `200` with `state` `unavailable` and no counts

#### Scenario: Unauthenticated
- **WHEN** the endpoint is requested without admin authentication while admin authentication is enabled
- **THEN** the response is `401`

### Requirement: Admin history store clear endpoint
`POST /api/admin/history-store/clear` SHALL require admin authentication and accept `dataset` (`all` | `prices` | `iv`), an optional `symbol` (any accepted notation, matched by its canonical form), an optional `provider`, an optional `interval` (`1h` | `4h` | `1d` | `1w`, price series only) and `confirm`. Without `confirm: true` the request SHALL be rejected with 422 and nothing SHALL be deleted. The endpoint SHALL delete the matching series with their rows, return the number of deleted series and rows, and write an audit log entry. With a disabled or unavailable store it SHALL respond with 503.

#### Scenario: Clear one symbol
- **WHEN** an admin posts `{"dataset": "prices", "symbol": "AAPL", "confirm": true}`
- **THEN** all price series of `AAPL` are deleted for every provider, IV series of `AAPL` remain, and the next daily-history request for `AAPL` loads the full range from the provider

#### Scenario: Clear one interval
- **WHEN** an admin posts `{"dataset": "prices", "provider": "ibkr", "interval": "1h", "confirm": true}`
- **THEN** the hourly price series of `ibkr` are deleted and its daily series remain

#### Scenario: Missing confirmation
- **WHEN** the body lacks `confirm: true`
- **THEN** the response is 422 and no row is deleted

#### Scenario: Index notation
- **WHEN** an admin posts `{"dataset": "all", "symbol": "^SPX", "confirm": true}`
- **THEN** the series stored under `I:SPX` are deleted

### Requirement: Admin UI history store card
The Admin UI Settings page SHALL show a "History Store" card with the state, the series and row counts per dataset, the newest synchronisation time, and a "Clear" action. The action SHALL open a dialog to choose dataset, optional symbol, optional provider and optional interval, SHALL require ticking an acknowledgement before the request can be sent, and SHALL show the number of deleted series and rows afterwards. With a disabled store the card SHALL state that `DATABASE_URL` is not configured and SHALL offer no action. With an unavailable store it SHALL state that the database cannot be reached and SHALL disable the action.

#### Scenario: Clearing from the UI
- **WHEN** an admin opens the dialog, selects `prices`, enters `AAPL`, ticks the acknowledgement and confirms
- **THEN** the series are deleted and the card shows the deleted counts and the updated totals

#### Scenario: Store not configured
- **WHEN** the store is disabled
- **THEN** the card shows that it is not configured and has no "Clear" button

#### Scenario: Database unreachable
- **WHEN** the store is unavailable
- **THEN** the card shows that the database cannot be reached and the "Clear" button is disabled

### Requirement: History store metric
The system SHALL expose the counter `mdh_history_store_reads_total` with the labels `dataset` (`prices` | `iv`) and `result` (`store`, `tail_sync`, `backfill`, `full_load`, `reload`, `stale`, `fallback_provider`, `bypass`), incremented once per served request. `fallback_provider` counts responses built from another provider's series. `bypass` counts requests answered from the provider because the store was disabled or unavailable. The metric SHALL NOT carry a symbol or provider label.

#### Scenario: Request answered from the store
- **WHEN** a daily-history request is answered without a provider call
- **THEN** `mdh_history_store_reads_total{dataset="prices",result="store"}` increases by 1

#### Scenario: Split detected
- **WHEN** a tail synchronisation triggers a reload of the series
- **THEN** the counter with `result="reload"` increases by 1

### Requirement: Optional Docker Compose PostgreSQL service
`docker-compose.yml` SHALL define a `postgres` service in the Compose profile `postgres`, with a named volume, a healthcheck and no published host port, on the internal network. Without that profile the stack SHALL start without PostgreSQL and with the history store disabled. With the profile and `DATABASE_URL` set in `.env`, MDH SHALL wait for a healthy database and use the store. `.env.example` and `doc/deployment.md` SHALL document `DATABASE_URL` as optional, the three `HISTORY_STORE_*` settings, how to start with the profile, that Kubernetes deployments provide the database outside this repository, the provider setting `history_store_intervals`, and a recommended volume size of 5 Gi (10 Gi when hourly bars are stored).

#### Scenario: Local start without PostgreSQL
- **WHEN** a developer runs `docker compose up -d` with a `.env` copied from `.env.example`
- **THEN** no `postgres` container is started, MDH reports the history store as disabled and serves all endpoints

#### Scenario: Local start with PostgreSQL
- **WHEN** a developer sets `DATABASE_URL` in `.env` and runs `docker compose --profile postgres up -d`
- **THEN** MDH reports the history store as connected

#### Scenario: Data survives a restart
- **WHEN** the stack with the profile is stopped and started again
- **THEN** a daily-history request for a previously loaded symbol while the market is settled is answered without a provider call
