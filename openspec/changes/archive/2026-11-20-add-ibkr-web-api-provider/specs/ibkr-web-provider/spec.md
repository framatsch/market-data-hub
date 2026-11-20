## ADDED Requirements

### Requirement: IBKR Web API provider registration
The system SHALL provide a provider `ibkrweb` that talks to the IBKR Client Portal Web API through a Client Portal Gateway (CPGW) at `<base_url>/v1/api` and implements `BasePriceProvider`, `BaseOptionsProvider`, `BaseCompanyProvider` and `BaseVolatilityProvider`. It SHALL NOT implement `BaseNewsProvider`. It SHALL be part of `KNOWN_PROVIDERS`, disabled by default, and enabled, configured and reloaded without restart like the other providers. It SHALL store no IBKR credentials. Every response it produces SHALL carry `provider: "ibkrweb"`. The existing provider `ibkr` (TWS API) SHALL remain unchanged.

#### Scenario: Enable the provider
- **WHEN** an admin enables `ibkrweb`
- **THEN** the registry loads it without a restart and `GET /providers` lists it under `prices`, `options`, `companies` and `volatility`, and not under `news`

#### Scenario: Both IBKR providers available
- **WHEN** `ibkr` and `ibkrweb` are both enabled
- **THEN** `GET /prices/AAPL/last?provider=ibkr` is served by the TWS API and `GET /prices/AAPL/last?provider=ibkrweb` by the Web API

#### Scenario: News not offered
- **WHEN** a client calls `GET /companies/AAPL/news?provider=ibkrweb`
- **THEN** the system answers as for any provider without the news interface, without an upstream request

### Requirement: Functional parity with the TWS provider
For every method that both `ibkr` and `ibkrweb` implement, `ibkrweb` SHALL return the same response model with the same field semantics, units, canonical symbols, `source_instrument` rules, `option_id` format and error codes as `ibkr`. Its support sets SHALL equal those of `ibkr` except for the gaps declared in this specification: `price_sec_types` and `price_history_sec_types` = `{stock, etf, index, future}`, `option_underlying_sec_types` = `{stock, etf}`, `native_intervals` = `{1m, 2m, 5m, 15m, 30m, 1h, 1d, 1w}`, `volatility_tenors` = `{30}`. `volatility_sec_types` SHALL contain `future` and `volatility_history_sec_types` SHALL be non-empty only after the spike recorded in `design.md` has verified them. A shared parity test suite SHALL run the same assertions on response shapes and error codes against both providers using recorded fixtures.

#### Scenario: Same quote shape
- **WHEN** `GET /prices/AAPL/last` is requested once with `provider=ibkr` and once with `provider=ibkrweb`
- **THEN** both responses have the same fields, `currency: "USD"`, a Decimal `price`, `bid`, `ask`, `volume` and `is_market_open`, and differ only in values and `provider`

#### Scenario: Same option symbol format
- **WHEN** an option chain for AAPL expiring 2026-12-18 is requested from both providers
- **THEN** the call with strike 200 has `symbol` `AAPL  261218C00200000` in both responses

#### Scenario: Declared gap answered explicitly
- **WHEN** a capability is not supported by `ibkrweb` (e.g. IV history while `volatility_history_sec_types` is empty)
- **THEN** the system responds with HTTP 501 `CAPABILITY_NOT_SUPPORTED` without an upstream request, never with an empty result

### Requirement: CPGW connection configuration
`ibkrweb` SHALL read `base_url` (default `https://127.0.0.1:5000`), `verify_tls` (default `false`), `ca_bundle` (optional path), `account_id` (optional), `compete` (default `false`), `market_data_type` (1–4, default 3), `max_streams` (default 80) and `login_url` (optional HTTPS URL a browser uses to open the gateway login, default `base_url`) from `connection_config`, with `IBKRWEB_*` environment defaults. It SHALL send a `User-Agent` header on every request and keep the gateway's session cookies. `verify_tls = false` SHALL only be accepted for loopback hosts and the compose service host `ibkr-cpgw`; for other hosts saving the config SHALL fail with 422 unless `verify_tls` is `true` or `ca_bundle` is set. A change of `base_url`, `verify_tls` or `ca_bundle` SHALL close the HTTP client and reset the session state.

#### Scenario: Default local gateway
- **WHEN** `ibkrweb` is enabled without custom `connection_config`
- **THEN** it requests `https://127.0.0.1:5000/v1/api/...` without certificate verification

#### Scenario: Remote host without verification rejected
- **WHEN** an admin saves `base_url = https://10.0.0.5:5000` with `verify_tls = false` and no `ca_bundle`
- **THEN** the save fails with HTTP 422 naming `verify_tls`

#### Scenario: Endpoint change resets the session
- **WHEN** `base_url` is changed while the session is `ready`
- **THEN** the HTTP client is closed, the state becomes unknown and the next request re-checks the session

### Requirement: Brokerage session lifecycle
`ibkrweb` SHALL track the session states `unreachable`, `login_required`, `competing`, `brokerage_pending` and `ready` from `POST /iserver/auth/status` and `POST /tickle`. When the gateway reports `connected: true` and `authenticated: false`, the provider SHALL call `POST /iserver/auth/ssodh/init` with `{"publish": true, "compete": <compete>}`, wait 2 seconds and call `GET /iserver/accounts` until it returns a non-empty list or `IBKRWEB_SESSION_INIT_TIMEOUT_SECONDS` (default 15) expire; only then SHALL the state be `ready` and `/iserver` market data requests be sent. Initialisation SHALL be serialised so that at most one `ssodh/init` is in flight. When `account_id` is set and not in the account list, the state SHALL still be `ready` and a WARNING SHALL be logged.

- `unreachable` SHALL be answered with `PROVIDER_CONNECTION_ERROR` naming `base_url`.
- `login_required` (HTTP 401 or `connected: false`) SHALL be answered with `PROVIDER_NOT_AVAILABLE`, `details.reason = "login_required"` and `details.login_url = <login_url or base_url>`; while in this state the provider SHALL NOT send market data requests and SHALL only probe through the keep-alive.
- `competing` (`competing: true` while `compete = false`) SHALL be answered with `PROVIDER_NOT_AVAILABLE`, `details.reason = "competing_session"` and a hint that another IBKR platform with the same username holds the brokerage session.

#### Scenario: First request after login
- **WHEN** the user has logged in at the gateway, the brokerage session is not yet initialised and `GET /prices/AAPL/last?provider=ibkrweb` arrives
- **THEN** the provider calls `ssodh/init` once, waits 2 s, receives a non-empty `/iserver/accounts`, and then serves the quote

#### Scenario: Concurrent first requests
- **WHEN** five requests arrive while the state is `brokerage_pending`
- **THEN** exactly one `ssodh/init` is sent and all five proceed after the session is `ready`

#### Scenario: Not logged in
- **WHEN** the gateway answers HTTP 401
- **THEN** the request fails with HTTP 503 `PROVIDER_NOT_AVAILABLE`, `details.reason: "login_required"`, `details.login_url: "https://127.0.0.1:5000"`, and following requests fail the same way without upstream market data requests until the keep-alive sees a session

#### Scenario: TWS session of the same user active
- **WHEN** the auth status reports `competing: true` and `compete` is `false`
- **THEN** requests fail with `PROVIDER_NOT_AVAILABLE`, `details.reason: "competing_session"`, and no `ssodh/init` with `compete: true` is sent

#### Scenario: Gateway not running
- **WHEN** the connection to `base_url` is refused
- **THEN** the request fails with `PROVIDER_CONNECTION_ERROR` and the message names the base URL

### Requirement: Session keep-alive and recovery
While `ibkrweb` is enabled, a background task SHALL send `POST /tickle` every `IBKRWEB_TICKLE_INTERVAL_SECONDS` (default 60, minimum 5) and update the session state, `ssoExpires` and the auth status from its response. The task SHALL start when the provider is loaded and SHALL be cancelled by `close()`. When the tickle reports `connected: true, authenticated: false` (idle timeout, nightly IServer reset) the task SHALL re-run the brokerage initialisation at most once per interval. When it reports no session it SHALL set `login_required`. Every state transition SHALL be logged once (WARNING for transitions away from `ready`, INFO for transitions to `ready`) and exported as gauge `mdh_provider_session_state{provider="ibkrweb", state=...}`. When `IBKRWEB_ALERT_WEBHOOK_URL` is set, a transition to `login_required` SHALL post `{"text": "IBKR Client Portal Gateway login required — log in at <base_url>"}` once as a fire-and-forget task whose failure is only logged.

#### Scenario: Session kept alive while idle
- **WHEN** no client request arrives for 30 minutes and the session was `ready`
- **THEN** the tickle task has sent about 30 tickles and the session is still `ready`

#### Scenario: Recovery after the nightly reset
- **WHEN** after 01:00 US/Eastern the tickle reports `connected: true, authenticated: false`
- **THEN** the task re-initialises the brokerage session and the state returns to `ready` without an admin action

#### Scenario: Daily login expired
- **WHEN** the tickle receives HTTP 401
- **THEN** the state becomes `login_required`, one WARNING is logged, the gauge is updated and the webhook is called once

#### Scenario: Login picked up automatically
- **WHEN** the user logs in again at the gateway while the state is `login_required`
- **THEN** the next tickle detects the session, initialises the brokerage session and the state becomes `ready`

#### Scenario: Disable stops the task
- **WHEN** `ibkrweb` is disabled
- **THEN** `close()` cancels the tickle task, closes the HTTP client and no further tickles are sent

### Requirement: Web API pacing
All requests of `ibkrweb` SHALL pass a token bucket with `rate_limit_per_sec` from the runtime config (default 6 for `ibkrweb`). Requests to `/iserver/marketdata/history` SHALL additionally pass a 50-per-minute sliding window, `/tickle` SHALL be sent at most once per second and `/sso/validate` at most once per minute. HTTP 429 SHALL NOT be retried; it SHALL start a pause of `IBKRWEB_PENALTY_SECONDS` (default 900) during which every request, including the keep-alive, fails with `PROVIDER_TIMEOUT`, `details.reason = "rate_limited"` and `details.retry_after_seconds`, without an upstream request. Every upstream request SHALL increment `mdh_provider_upstream_requests_total{provider="ibkrweb"}`.

#### Scenario: Burst of quotes
- **WHEN** 40 last-price requests for different symbols arrive at once
- **THEN** the provider sends at most 6 requests per second to the gateway

#### Scenario: Long history
- **WHEN** a history request needs 70 windows
- **THEN** no more than 50 history requests are sent within any 60-second window

#### Scenario: Penalty box
- **WHEN** the gateway answers HTTP 429
- **THEN** the request fails with `PROVIDER_TIMEOUT` and `details.reason: "rate_limited"`, and for the next 900 seconds all `ibkrweb` requests fail the same way without upstream requests

### Requirement: Contract resolution
`ibkrweb` SHALL translate `(root, sec_type)` to a conid: stock/etf through `GET /trsrv/stocks?symbols=<root>` (the US contract of the `STK` entry); index through `GET /iserver/secdef/search?symbol=<root'>&secType=IND` using the shared IBKR index root overrides (`DJI` → `INDU`) and index exchange table (Web `INDU` uses CME); future through `GET /trsrv/futures?symbols=<root>`, selecting the contract with the nearest effective last trade date on or after today + 7 days (`ltd` capped at `expirationDate` when both are present) and checking its contract-info exchange against the shared futures exchange table (an unknown root on several exchanges SHALL fail with `DATA_VALIDATION_ERROR` as with `ibkr`). Before `/iserver/secdef/strikes` or `/iserver/secdef/info` the provider SHALL have called `/iserver/secdef/search` for the same root in the current process. Resolved conids SHALL be cached in process and, when Redis is available, under `mdh:ibkrweb:conid:{sec_type}:{root}` (30 days for stock/etf/index, until the roll cutoff for futures). An unknown root SHALL fail with `DATA_NOT_FOUND`.

#### Scenario: Stock conid
- **WHEN** `GET /prices/AAPL/last?provider=ibkrweb` is requested
- **THEN** the provider resolves the US NASDAQ contract of AAPL (conid 265598) and caches it

#### Scenario: Cached conid
- **WHEN** the same symbol is requested again within 30 days
- **THEN** no contract request is sent

#### Scenario: Index with deviating root
- **WHEN** `GET /prices/I:DJI/last?provider=ibkrweb` is requested
- **THEN** the provider searches the index `INDU` and the response `symbol` is `I:DJI`

#### Scenario: Front-month future
- **WHEN** `GET /prices/F:ES/last?provider=ibkrweb` is requested on 2026-12-15 and the December contract's last trade date is 2026-12-18
- **THEN** the March 2027 contract is used and `source_instrument` is its local symbol (`ESH7`)

### Requirement: Last price over the Web API
`get_last_price` SHALL request `GET /iserver/marketdata/snapshot` for the resolved conid with fields `31,84,86,87,7762,70,71,7295,7296,7741,6509`, treating the first response as pre-flight and polling every 0.5 s up to `IBKRWEB_SNAPSHOT_TIMEOUT_SECONDS` (default 4) until a price is present. `price` SHALL be field `31`, else `7296`, else `7741`; `bid`/`ask`/`open`/`high`/`low` from `84`/`86`/`7295`/`70`/`71`; volume SHALL prefer `7762` over `87`. String values SHALL be parsed after removing thousands separators and status prefixes, expanding compact `K`/`M` quantities where applicable, and empty or non-numeric values SHALL be `null`. `timestamp` SHALL be `_updated` (epoch ms, UTC). `is_market_open` SHALL follow the trading-schedule requirement. When no price arrives, the provider SHALL fall back to the last daily close of the same conid from `/iserver/marketdata/history` (`period=1w`, `bar=1d`), as `ibkr` does, and SHALL raise `PROVIDER_NOT_ENTITLED` only when the fallback is exhausted and an entitlement problem was observed.

#### Scenario: Quote with bid and ask
- **WHEN** the snapshot returns `31: "168.42"`, `84: "168.41"`, `86: "168.42"`, `87: "1,300"`, `6509: "RpB"`
- **THEN** the quote has `price 168.42`, `bid 168.41`, `ask 168.42`, `volume 1300`

#### Scenario: Pre-flight without values
- **WHEN** the first snapshot response only contains `conid` and `conidEx`
- **THEN** the provider polls again and returns the quote from the first response that contains a price

#### Scenario: Index stays an index in the fallback
- **WHEN** `GET /prices/I:SPX/last?provider=ibkrweb` gets no snapshot price
- **THEN** the history fallback uses the SPX index conid, not a stock conid

### Requirement: Market data type and entitlements over the Web API
`ibkrweb` SHALL accept `market_data_type` 1–4 per request and as config default, and SHALL check the first character of snapshot field `6509` against it: type 1 accepts only `R`; type 2 accepts `R` and `Z`; types 3 and 4 accept `R`, `D`, `Z` and `Y`. An unaccepted availability with type 1 SHALL raise `PROVIDER_NOT_ENTITLED` with the hint that live data needs a subscription. With types 2–4 and `IBKR_FALLBACK_ON_SUBSCRIPTION_ERROR = true`, the historical close fallback SHALL be tried first. `N` in snapshots or history SHALL be treated as not entitled; `O` SHALL raise `PROVIDER_NOT_ENTITLED` with the hint to complete the Market Data API Acknowledgement in Client Portal settings. History `mdAvailability="S"` SHALL NOT be interpreted as a snapshot availability code. Entitlement errors SHALL carry `details.symbol` in canonical form and `details.instrument`.

#### Scenario: Live requested, delayed delivered
- **WHEN** `GET /prices/AAPL/last?provider=ibkrweb&market_data_type=1` is requested and `6509` is `DpB`
- **THEN** the system responds with HTTP 403 `PROVIDER_NOT_ENTITLED` and `details.symbol: "AAPL"`

#### Scenario: Delayed accepted
- **WHEN** the default `market_data_type` 3 is used and `6509` is `DpB`
- **THEN** the delayed quote is returned

#### Scenario: API acknowledgement missing
- **WHEN** `6509` starts with `O`
- **THEN** the system responds with `PROVIDER_NOT_ENTITLED` and a hint naming the Market Data API Acknowledgement

### Requirement: Snapshot stream budget
`ibkrweb` SHALL track the conids for which a snapshot stream was opened. When a request would raise their number above `max_streams` (default 80), the provider SHALL send one `GET /iserver/marketdata/unsubscribeall` and clear the set before the request. It SHALL NOT send single unsubscribes. Snapshot conids SHALL be sent in batches of at most `IBKRWEB_SNAPSHOT_BATCH_SIZE` (default 50).

#### Scenario: Stream limit reached
- **WHEN** 78 streams are open and an option chain needs 10 new conids
- **THEN** one `unsubscribeall` is sent, the set is cleared and the 10 conids are pre-flighted

### Requirement: Historical prices over the Web API
`get_historical_prices` SHALL request `GET /iserver/marketdata/history` with `source=Last`, `bar` mapped from the canonical interval (`1m`→`1min`, `2m`→`2min`, `5m`→`5min`, `15m`→`15min`, `30m`→`30min`, `1h`→`1h`, `1d`→`1d`, `1w`→`1w`), `outsideRth = extended_hours`, and windows that each yield at most 1,000 bars and respect the documented step-size table, walking backwards from `end` (`startTime` in UTC `YYYYMMDD-hh:mm:ss`, `direction=-1`) until `start` is covered or a window returns no bars. Bars SHALL be de-duplicated by `t`, clipped to `[start, end]` and returned in ascending order with the same `PriceBar` time conventions as `ibkr`. An unsupported interval SHALL fail like in `ibkr`. A range that needs more than 40 windows for the interval SHALL fail with `DATA_VALIDATION_ERROR` before any history request, so one call cannot exhaust the shared 50-per-minute history budget. HTTP 400 SHALL be `DATA_VALIDATION_ERROR`, 500/503 `PROVIDER_CONNECTION_ERROR`, an empty range an empty list.

#### Scenario: One year of daily bars
- **WHEN** `GET /prices/AAPL/history?provider=ibkrweb&interval=1d&start=2025-11-19&end=2026-11-19` is requested
- **THEN** one history request with `bar=1d` and a period covering the range is sent and about 250 ascending bars are returned

#### Scenario: Intraday range above 1,000 bars
- **WHEN** 10 trading days of `1m` bars are requested
- **THEN** the range is split into windows of at most 1,000 bars, the windows are merged without duplicates and the result covers the whole range

#### Scenario: Extended hours
- **WHEN** `extended_hours=true` is requested
- **THEN** the history requests carry `outsideRth=true`

### Requirement: Futures history over the Web API
For `F:<ROOT>` history `ibkrweb` SHALL use the current front-month contract (no continuous series; the Web API lists no expired futures) and SHALL set `source_instrument` to its local symbol. The provider details in the admin API and the README SHALL document this deviation from `ibkr` (`ContFuture`).

#### Scenario: Futures history
- **WHEN** `GET /prices/F:ES/history?provider=ibkrweb&interval=1d` is requested
- **THEN** the bars of the front-month contract are returned with `source_instrument` e.g. `ESZ6`

### Requirement: Market-open status over the Web API
`is_market_open` SHALL be derived from `GET /contract/trading-schedule?conid=<conid>`: `true` when the current time in `exchange_time_zone` lies within an `extended_hours` session of today, `false` when today has no schedule entry or the time is outside all sessions, `null` when the schedule cannot be loaded. The schedule SHALL be cached per conid and exchange date in process.

#### Scenario: Holiday
- **WHEN** today is a US market holiday and the schedule has no entry for today
- **THEN** `is_market_open` is `false`

#### Scenario: Schedule unavailable
- **WHEN** the schedule request fails
- **THEN** the quote is returned with `is_market_open: null`

### Requirement: Option chains over the Web API
`get_option_chain` SHALL resolve the underlying via `/iserver/secdef/search`, load strikes via `GET /iserver/secdef/strikes?conid&sectype=OPT&month=<MMMYY>`, filter them by `min_strike`/`max_strike`, resolve each strike via `GET /iserver/secdef/info?conid&sectype=OPT&month&strike&exchange=SMART` (adding `right` when only one is requested) and keep only contracts with the requested right and `maturityDate` equal to the expiry. It SHALL request snapshots with fields `31,84,86,87,7762,7296,7633,7308,7309,7310,7311,7638,6509` (option timeout `IBKRWEB_OPTION_SNAPSHOT_TIMEOUT_SECONDS`, default 10, done when at least 50 % of the contracts have data). Option conids SHALL be cached until the day after expiry under `mdh:ibkrweb:optconid:{root}:{yyyymmdd}:{C|P}:{strike}`. Each `OptionQuote` SHALL have `symbol` = OCC local symbol, `implied_volatility` = `7633` ÷ 100, `delta`/`gamma`/`theta`/`vega` from `7308`/`7309`/`7310`/`7311`, `open_interest` from `7638`, `price` = last, else close, else 0, and `bid`/`ask` `null` when absent. An expiry without contracts SHALL return an empty chain.

#### Scenario: Chain with Greeks
- **WHEN** `GET /options/AAPL/chain?provider=ibkrweb&expiry=2026-12-18&min_strike=190&max_strike=210` is requested
- **THEN** the result contains calls and puts for the listed strikes with IV as decimal fraction, Greeks and open interest

#### Scenario: Weekly expiries in the same month
- **WHEN** `secdef/info` for strike 200 in `DEC26` returns contracts for 2026-12-04, 2026-12-11 and 2026-12-18
- **THEN** only the 2026-12-18 contracts are part of the chain

#### Scenario: Warm chain
- **WHEN** the same chain is requested again
- **THEN** no `secdef/info` requests are sent, only snapshots

#### Scenario: Unknown expiry
- **WHEN** the expiry has no listed contracts
- **THEN** the result is an empty chain with `provider: "ibkrweb"`

### Requirement: Option quote over the Web API
`get_option_quote(symbol, option_id)` SHALL parse `option_id` in OCC local-symbol format (root padded to 6, `YYMMDD`, `C`/`P`, strike × 1000 in 8 digits), resolve the contract through the option conid cache or `/iserver/secdef/search` + `/iserver/secdef/info`, and return one snapshot mapped as in option chains. An unparseable `option_id` or an unknown contract SHALL fail with `DATA_NOT_FOUND`.

#### Scenario: Quote by OCC symbol
- **WHEN** `GET /options/AAPL/quote/AAPL  261218C00200000?provider=ibkrweb` is requested
- **THEN** the AAPL 2026-12-18 200 call is resolved and its quote returned with the same `symbol`

#### Scenario: Malformed id
- **WHEN** `option_id` is `AAPL-200C`
- **THEN** the request fails with `DATA_NOT_FOUND`

### Requirement: Implied volatility over the Web API
`get_implied_volatility` SHALL request snapshot field `7283` for the resolved underlying conid, poll until a positive value arrives or `IBKRWEB_IV_TIMEOUT_SECONDS` (default 10) expire, and return a `VolatilitySnapshot` with `iv = quantize_iv(value / 100)` at tenor 30, `method: "provider_model_30d"`, `source_instrument`, `underlying`, `underlying_name` from `/iserver/contract/{conid}/info`, `market`, and `as_of` from `_updated` in the exchange time zone. A timeout SHALL be `DATA_NOT_FOUND` with `reason: "no_iv_data"`; availability `N`/`O` SHALL be `PROVIDER_NOT_ENTITLED`. The `ric` override SHALL be rejected as with `ibkr`. `get_implied_volatility_history` SHALL raise `CAPABILITY_NOT_SUPPORTED` without an upstream request while `volatility_history_sec_types` is empty; if the spike verified an IV history source, it SHALL behave like the `ibkr` history (tenor 30, stock/etf/index, ascending daily points in decimal fractions).

#### Scenario: Snapshot IV in fractions
- **WHEN** field `7283` is `"25.19%"` for AAPL
- **THEN** the response has `iv: 0.2519` at tenor 30 and `method: "provider_model_30d"`

#### Scenario: IV history not available
- **WHEN** `GET /volatility/AAPL/history?provider=ibkrweb` is requested and no IV history source was verified
- **THEN** the system responds with HTTP 501 `CAPABILITY_NOT_SUPPORTED` without an upstream request

### Requirement: Company data over the Web API
`get_company_profile` SHALL resolve the stock conid and return `name` from `company_name` of `/iserver/contract/{conid}/info` (else the `/trsrv/stocks` name), `exchange` as the listing exchange, `currency`, and `industry`/`sector` from `industry`/`category` when present. An unknown symbol SHALL fail with `DATA_NOT_FOUND`. `search_companies(query)` SHALL use `GET /iserver/secdef/search?symbol=<query>&name=true` and return the `STK` hits as `CompanySummary` (symbol, name, exchange), an empty list when nothing matches. A name search SHALL NOT be used for the same root before option strikes are requested (the documented `name=true` side effect); option resolution SHALL always issue its own search without `name`.

#### Scenario: Profile with industry
- **WHEN** `GET /companies/AAPL?provider=ibkrweb` is requested
- **THEN** the profile has `name: "APPLE INC"`, `exchange: "NASDAQ"`, `currency: "USD"` and `industry: "Computers"`

#### Scenario: Search by name
- **WHEN** `GET /companies/search?q=apple&provider=ibkrweb` is requested
- **THEN** the result contains AAPL

### Requirement: Web API error mapping
`ibkrweb` SHALL map gateway responses as follows: HTTP 401 → session state `login_required` and `PROVIDER_NOT_AVAILABLE`; 400 → `DATA_VALIDATION_ERROR` with the gateway's `error` text; 404 or an empty contract result → `DATA_NOT_FOUND`; 429 → penalty pause and `PROVIDER_TIMEOUT`; 500 and 503 → `PROVIDER_CONNECTION_ERROR` with the gateway's `error` text; request timeout → `PROVIDER_TIMEOUT`; a response that does not match the expected JSON shape → `PROVIDER_ERROR`. A 500/503 SHALL additionally trigger a session status check before the next request (at most once per 30 seconds); it SHALL NOT change the session state by itself, so requests already in flight are not failed and open streams are not forgotten. The provider SHALL never return an error as an empty result.

#### Scenario: Nightly reset
- **WHEN** a request at 01:01 US/Eastern receives HTTP 503
- **THEN** the request fails with `PROVIDER_CONNECTION_ERROR` and the next request first re-checks the session status

#### Scenario: Unexpected payload
- **WHEN** the snapshot endpoint answers HTML instead of JSON
- **THEN** the request fails with `PROVIDER_ERROR`
