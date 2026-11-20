## Context

`ibkr` (`app/providers/ibkr.py`, ~1,900 lines) talks to TWS or IB Gateway through `ib_async`. It implements prices, options, companies, news and volatility. Its behaviour is fixed by the specs `provider-symbol-mapping`, `provider-entitlement-errors`, `underlying-implied-volatility`, `provider-connection-test`, `ibkr-connection-ui` and `derived-price-intervals`.

The Client Portal Web API (documentation checked on 2026-11-19, Markdown via the `.md` suffix of each page):

| Item | Documented value |
|---|---|
| Gateway | Java program `clientportal.gw`, `bin/run.sh root/conf.yaml`, listens on `https://localhost:5000` (`listenPort` in `conf.yaml`), self-signed certificate; base path `/v1/api` |
| Login | Browser login on the gateway page; "Interactive Brokers does not support an automated authentication process"; re-login daily; login and all API calls on the machine where the CPGW was authenticated |
| Sessions | Two tiers: read-only SSO session (non-`/iserver` endpoints) and brokerage session (`/iserver`, all market data). One brokerage session per username across TWS, Client Portal, IBKR Mobile and the Web API |
| Brokerage session start | `POST /iserver/auth/ssodh/init` `{"publish": true, "compete": <bool>}`, then wait 2 s, then `GET /iserver/accounts` must be non-empty |
| Status | `POST /iserver/auth/status` with JSON `{}` → `authenticated`, `competing`, `connected`, `message`, `fail`; `GET /sso/validate` (1/min) → `USER_NAME`, `LOGIN_TYPE` (1 live, 2 paper), `features` |
| Keep-alive | Brokerage session ends after 5 min without `/iserver` traffic; `POST /tickle` about every 60 s (1/s limit), returns `ssoExpires` (ms) and the auth status |
| Logout | `POST /logout` |
| Maintenance | `/iserver` briefly unavailable each night ≈ 01:00 local region time (North America 01:00 US/Eastern, Europe 01:00 CEST); Web API maintenance on Saturday evenings |
| Pacing | Global 10 requests/s; `/iserver/marketdata/snapshot` 10/s; `/iserver/marketdata/history` 10/s or 50/min; `/tickle` 1/s; `/sso/validate` 1/min. HTTP 429 → IP in a penalty box for 15 min, repeat violators can be blocked permanently |
| Snapshot | `GET /iserver/marketdata/snapshot?conids=…&fields=…`; `/iserver/accounts` must have been called; first request is a pre-flight that opens the stream and usually returns no values; values update every 500 ms; field `6509` = availability (`R` real-time, `D` delayed, `Z` frozen, `Y` frozen delayed, `N` not subscribed, `O` Market Data API acknowledgement missing) |
| Snapshot fields used | `31` last, `84` bid, `86` ask, `87` volume, `70`/`71` high/low, `7295` open, `7296` close, `7741` prior close, `7283` option implied vol. % (underlying), `7633` implied vol. % (option strike), `7308`–`7311` delta/gamma/theta/vega, `7638` option open interest, `6509` availability, `_updated` epoch ms |
| Unsubscribe | `POST /iserver/marketdata/unsubscribe {"conid": n}` (500 `unknown` when no stream is open), `GET /iserver/marketdata/unsubscribeall` |
| History | `GET /iserver/marketdata/history?conid&period&bar&exchange&outsideRth&startTime&direction&source`; `source` = `Last` (default), `Midpoint`, `Bid_Ask`; max 1,000 bars per response; bar `t` = epoch ms of the bar start; periods `min`/`h`/`d`/`w`/`m`/`y`, bars `S`/`min`/`h`/`d`/`w`/`m`; step-size table limits bar size per period |
| Contracts | `GET /iserver/secdef/search?symbol=…[&name=true][&secType=…]` (required before strikes/info), `GET /trsrv/stocks?symbols=…`, `GET /trsrv/futures?symbols=…` (non-expired contracts with `conid`, `ltd`, `expirationDate`), `GET /iserver/secdef/strikes?conid&sectype=OPT&month=MMMYY[&exchange]`, `GET /iserver/secdef/info?conid&sectype=OPT&month&strike&right[&exchange]`, `GET /iserver/contract/{conid}/info` (`company_name`, `industry`, `category`, `currency`, `local_symbol`, `r_t_h`) |
| Trading hours | `GET /contract/trading-schedule?conid=…[&exchange]` → `exchange_time_zone`, per date `extended_hours` and `liquid_hours` with epoch `opening`/`closing`; non-trading days are omitted |
| Errors | 400 (`error` prefixed `Bad Request:`), 401 (no or expired session), 429, 500 (`error` reason), 503 (internal timeout > 10 s) |

Not in the Web API documentation: a historical news endpoint, an implied-volatility `source` for history (TWS `OPTION_IMPLIED_VOLATILITY`), continuous futures (`ContFuture`), a per-request market data type (TWS `reqMarketDataType`).

## Goals / Non-Goals

**Goals:**
- The same MDH functionality as `ibkr` over the CPGW, with identical response shapes and error semantics, so that a client can switch from `provider=ibkr` to `provider=ibkrweb` (or the admin switches the defaults) without code changes.
- Every gap is explicit: verified in a spike, declared in the support sets, answered with `CAPABILITY_NOT_SUPPORTED` or a documented deviation.
- A session lifecycle that survives the 5-minute idle timeout, the nightly IServer reset and the daily re-login without manual steps except the login itself.
- Never trigger IBKR's penalty box.

**Non-Goals:**
- Replacing or changing `ibkr`; automated/headless login (IBeam-like credential automation); OAuth 1.0a/2.0; websocket streaming; trading, portfolio, scanner or account endpoints; news.

## Decisions

### D1: Separate provider `ibkrweb`, not a transport switch inside `ibkr`

`ibkrweb` is a new provider with its own class, config, capabilities, admin card, metrics label and cache namespace. The registry, system defaults and `provider` parameters treat it like any other provider.

*Alternative*: one provider `ibkr` with `connection_config.api = tws | web`. Rejected: the two transports have different configuration fields, different support sets (news, IV history) and different failure modes (socket/client id vs. browser session), which the capability catalog derives from the provider class; the admin UI, the connection test and the metrics would need per-transport branches. A separate provider also allows running both side by side for the parity check (with two usernames, see D3).

Shared, transport-independent logic is extracted from `ibkr.py` into `app/providers/ibkr_common.py` without behaviour change: futures exchange table `_FUTURES_EXCHANGES`, index root overrides `_INDEX_ROOT_OVERRIDES`, index exchange table, front-month selection rule (nearest last trade date ≥ today + 7 days), trading-hours evaluation, OCC option symbol formatting/parsing, interval list, IV quantisation calls.

### D2: Parity matrix

| MDH method (`ibkr`) | TWS API | Web API (`ibkrweb`) | Parity |
|---|---|---|---|
| `get_last_price` stock/etf | `Stock(root, SMART, USD)`, `reqMktData` snapshot | conid via `/trsrv/stocks` (US listing) → snapshot `31,84,86,87,7762,70,71,7295,7296,7741,6509` | full |
| `get_last_price` index | `Index(root', exch)` | conid via `/iserver/secdef/search?symbol=root'&secType=IND`, exchange from the shared index table | full |
| `get_last_price` future | front-month `Future` from contract details | front month from `/trsrv/futures` (`ltd` ≥ today + 7 days), `source_instrument` = local symbol from `/iserver/contract/{conid}/info` | full |
| last-price fallback | historical daily close of the same contract | `/iserver/marketdata/history` `period=1w&bar=1d` of the same conid | full |
| `market_data_type` 1–4 | `reqMarketDataType` | not selectable; requested type checked against field `6509` (D6) | semantic |
| `is_market_open` | `reqContractDetails.tradingHours` | `/contract/trading-schedule` (D9) | full |
| `get_historical_prices` | `reqHistoricalData` `TRADES`, `useRTH` | `/iserver/marketdata/history` `source=Last`, `outsideRth`, chunked (D7) | full for stock/etf/index; future: front-month contract only (D8) |
| `get_option_chain` | `reqSecDefOptParams` + qualify + snapshots | `secdef/search` → `secdef/strikes` → `secdef/info` per strike → snapshot (D10) | full |
| `get_option_quote` | qualify by `localSymbol` | parse OCC symbol → `secdef/info` → snapshot | full |
| `get_implied_volatility` | tick 106, 30-day model | snapshot field `7283` ÷ 100 (D11) | full (future after spike) |
| `get_implied_volatility_history` | `OPTION_IMPLIED_VOLATILITY` bars | no documented source (D11) | gap → 501 unless the spike proves a source |
| `get_company_profile` | qualified contract `longName` | `/iserver/contract/{conid}/info` (`company_name`, `industry`, `category`, `currency`), listing exchange from `/trsrv/stocks` | full (plus industry/sector) |
| `search_companies` | qualify query as symbol | `/iserver/secdef/search?symbol=q&name=true`, STK hits | better (name search) |
| `get_company_news` | `reqHistoricalNews` | none | gap: `ibkrweb` does not implement `BaseNewsProvider` |
| `test_connection` | socket connect | session status (D4) | full |

"Parity" means: the same request returns the same model with the same field semantics, units, symbols and error codes; values may differ in the last digits because the two APIs sample at different moments.

### D3: Session model and single-session rule

The provider owns one `httpx.AsyncClient` (base URL `<base_url>/v1/api`, `verify=verify_tls or ca_bundle`, `User-Agent: market-data-hub/<version>`, cookie jar kept for the session). Session state:

| State | Detection | Behaviour |
|---|---|---|
| `unreachable` | connection refused / TLS / DNS error | `PROVIDER_CONNECTION_ERROR` "Client Portal Gateway not reachable at <base_url>" |
| `login_required` | HTTP 401, or auth status `connected: false` | fail fast with `PROVIDER_NOT_AVAILABLE`, `details.reason = "login_required"`, `details.login_url = <base_url>`; no `/iserver` request until the keep-alive sees a session |
| `competing` | auth status `competing: true` and `compete = false` | `PROVIDER_NOT_AVAILABLE`, `details.reason = "competing_session"` with the hint that another platform (TWS/IB Gateway, Client Portal, IBKR Mobile, or MDH's `ibkr` provider with the same username) holds the brokerage session |
| `brokerage_pending` | `connected: true`, `authenticated: false` | `POST /iserver/auth/ssodh/init` with `publish: true` and the configured `compete`, wait 2 s, `GET /iserver/accounts` until non-empty (max `IBKRWEB_SESSION_INIT_TIMEOUT_SECONDS`, default 15) |
| `ready` | `authenticated: true` and accounts loaded | requests proceed |

Initialisation is serialised by a lock (one `ssodh/init` at a time). `compete` defaults to `false` because `true` disconnects the user's TWS or IBKR Mobile brokerage session. Running `ibkr` and `ibkrweb` at the same time requires two IBKR usernames (each billed separately for market data); the admin UI warns when both are enabled.

`account_id` selects the account when `/iserver/accounts` returns several; it is not needed for market data and is only validated against the list.

### D4: Keep-alive, nightly reset and daily login

While `ibkrweb` is enabled a background task (started on registry load, cancelled in `close()`) sends `POST /tickle` every `IBKRWEB_TICKLE_INTERVAL_SECONDS` (default 60, minimum 5) and updates the state from the embedded auth status and `ssoExpires`. When the tickle shows `connected: true, authenticated: false` (after the nightly reset or an idle timeout) it re-runs the brokerage initialisation of D3 once per interval. When it shows no session (401 or `connected: false`) it switches to `login_required`, logs one WARNING per transition, sets the gauge `mdh_provider_session_state{provider="ibkrweb"}` and, if `IBKRWEB_ALERT_WEBHOOK_URL` is set, posts `{"text": "IBKR Client Portal Gateway login required — log in at <base_url>"}` once per transition (fire-and-forget, like Schwab). A successful login is picked up by the next tickle without an admin action.

*Alternative*: tickle only on demand before requests. Rejected: the brokerage session dies after 5 idle minutes and the first request after a quiet period would pay the init and the 2-second wait.

### D5: Pacing and the penalty box

All requests of the provider pass one async token bucket: `rate_limit_per_sec` from the runtime config, default 6 for `ibkrweb` (documented global limit 10; order-hub's `ibkrweb` provider defaults to 2, so both services together stay at 8 when they share one gateway, see D15). History requests additionally pass a 50-per-minute sliding window; `/tickle` and `/sso/validate` respect their own limits (1/s, 1/min). On any HTTP 429 the provider enters a pause of `IBKRWEB_PENALTY_SECONDS` (default 900, the documented penalty box) and answers every request during the pause with `PROVIDER_TIMEOUT` (`details.reason = "rate_limited"`, `details.retry_after_seconds`), including the keep-alive. No 429 is retried. The pause and the 429 count are exposed in the session endpoint and as metrics.

### D6: Market data type and entitlements

The Web API delivers what the username is entitled to; there is no `reqMarketDataType`. The provider keeps the parameter and the `market_data_type` config for interface parity and maps it to a check of field `6509` (first character):

| Requested | Accepted availability | Otherwise |
|---|---|---|
| 1 (live) | `R` | `PROVIDER_NOT_ENTITLED` (same strictness as `ibkr` Level 1) |
| 2 (frozen) | `R`, `Z` | historical close fallback, then `PROVIDER_NOT_ENTITLED` |
| 3 (delayed, default) | `R`, `D`, `Z`, `Y` | historical close fallback, then `PROVIDER_NOT_ENTITLED` |
| 4 (delayed frozen) | `R`, `D`, `Z`, `Y` | historical close fallback, then `PROVIDER_NOT_ENTITLED` |

`N` (not subscribed) and `O` (API acknowledgement missing) are entitlement errors; `O` carries the hint to sign the Market Data API Acknowledgement in Client Portal settings. `IBKR_FALLBACK_ON_SUBSCRIPTION_ERROR` applies to `ibkrweb` as well. A history response with `mdAvailability` `N` is an entitlement error.

### D7: Snapshots and open streams

A snapshot request sends all needed fields in one call and polls every 0.5 s until the required fields are present or the timeout expires (`IBKRWEB_SNAPSHOT_TIMEOUT_SECONDS` 4 for underlyings, `IBKRWEB_OPTION_SNAPSHOT_TIMEOUT_SECONDS` 10 for options; the same values as `ibkr`). Conids are sent in batches of `IBKRWEB_SNAPSHOT_BATCH_SIZE` (default 50, confirmed in the spike; 51 also worked, exact ceiling not measured). Required fields: a price (`31`, else `7296`, else `7741`) for quotes; bid or ask or last or close for at least 50 % of option contracts (as `ibkr`).

Opened streams are tracked. When a request would exceed `max_streams` (default 80, below IBKR's usual 100 market data lines), the provider issues one `GET /iserver/marketdata/unsubscribeall` and clears the set before the request. Polls run concurrently; only this bookkeeping is serialised, and `unsubscribeall` is sent only once no other poll is active (new polls wait while the budget is reset). After a brokerage re-initialisation the tracked streams are reset the same way. Single unsubscribes are not used (they cost a request each and fail with 500 for unknown streams).

Field values arrive as strings, possibly with thousands separators (`"1,300"`) and documented prefixes (`C`/`H` for close/halted on `31`); the parser strips them and treats empty or non-numeric values (including `N/A`) as `null`. Prefer unabridged volume in `7762`, falling back to `87`. Compact volume and open interest can include `K` or `M` suffixes and are rounded upstream.

### D8: History chunking and futures

Canonical intervals map to `bar`: `1m`→`1min`, `2m`→`2min`, `5m`→`5min`, `15m`→`15min`, `30m`→`30min`, `1h`→`1h`, `1d`→`1d`, `1w`→`1w`. For a range `[start, end]` the provider requests windows ending at `end` (`startTime` = window end in UTC `YYYYMMDD-hh:mm:ss`, `direction=-1`) with the largest `period` allowed by the step-size table for the bar and ≤ 1,000 bars, walking backwards until `start` is covered or a window returns no data; bars are de-duplicated by `t` and clipped to `[start, end]`. `extended_hours` maps to `outsideRth`. Bar `t` is epoch ms of the bar start; `PriceBar.start` follows the TWS time conventions (intraday timestamps, daily and weekly session dates at midnight). Volume: `v` × `volumeFactor` when present.

Futures history uses the current front-month contract (`F:ES` → e.g. `ESZ6`), with `source_instrument` set. The Web API lists no expired futures and has no continuous series, so the history ends at the listing of the front month for long ranges. This is a documented deviation from `ibkr` (`ContFuture`).

### D9: Market-open status

`is_market_open` uses `/contract/trading-schedule?conid=…`: open when now (in `exchange_time_zone`) is within an `extended_hours` session of today, closed when today has no entry or now is outside, `null` on error. This matches `ibkr`, whose `tradingHours` include the extended session. The schedule is cached per conid and exchange date in process.

### D10: Option chains

1. Underlying conid via `/iserver/secdef/search?symbol=<root>` (also required by IBKR before strikes/info; the search result is cached for the process lifetime per root).
2. `GET /iserver/secdef/strikes?conid&sectype=OPT&month=<MMMYY of expiry>`; strikes filtered by `min_strike`/`max_strike`.
3. For every remaining strike: `GET /iserver/secdef/info?conid&sectype=OPT&month&strike&exchange=SMART`; omit `right` when both rights are needed (verified), otherwise send it. Filter by requested right(s) and `maturityDate == expiry` (a month contains weeklies). Option conids are cached in Redis under `mdh:ibkrweb:optconid:{root}:{yyyymmdd}:{C|P}:{strike}` until the day after expiry.
4. Snapshot of all option conids with fields `31,84,86,87,7762,7296,7633,7308,7309,7310,7311,7638,6509`.

Mapping: `symbol` = OCC local symbol built from root, expiry, right and strike (identical to `ibkr`'s `localSymbol`, e.g. `AAPL  261218C00200000`), `implied_volatility` = `7633` ÷ 100, Greeks as delivered, `open_interest` = `7638`, `price` = last, else close, else 0, bid/ask `null` when absent. An expiry without strikes returns an empty chain, as `ibkr`.

Cost: with 40 distinct strikes a cold chain needs up to 40 info requests plus search, strikes and snapshot polling. A warm chain (conids cached) needs no info requests. The spike ruled out the one-request-per-month path: omitting `strike` returns HTTP 400 even when `right` is supplied.

`get_option_quote(symbol, option_id)` parses the OCC symbol (root, expiry, right, strike), resolves the conid through steps 1 and 3 (or the cache) and returns one snapshot mapped as above; an unparseable or unknown `option_id` is `DATA_NOT_FOUND`.

### D11: Implied volatility

Snapshot: field `7283` "Option Implied Vol. %" is IBKR's 30-day implied volatility of the underlying (the Web API counterpart of TWS tick 106); `iv = quantize_iv(value / 100)`, `method = "provider_model_30d"`, `tenor 30`, `as_of` from `_updated` in the exchange time zone, `underlying_name` from contract info. A missing value after the timeout is `DATA_NOT_FOUND` with `reason: no_iv_data`. Futures are declared in `volatility_sec_types` only if the spike returns a value for a front-month future.

History: the documented `source` values are `Last`, `Midpoint`, `Bid_Ask`. The spike tries the TWS names (`Option_Implied_Volatility`, `OPTION_IMPLIED_VOLATILITY`) once. Only if one of them returns plausible daily IV values for AAPL, SPY and SPX does `ibkrweb` declare `volatility_history_sec_types = {stock, etf, index}` (tenor 30) and implement history like `ibkr`; otherwise the set stays empty and `/volatility/{symbol}/history?provider=ibkrweb` answers 501 `CAPABILITY_NOT_SUPPORTED` without an upstream request. The decision and the recorded responses are written into this document (task 0.2).

### D12: Contract resolution and caches

| Type | Resolution | Cache |
|---|---|---|
| stock/etf | `/trsrv/stocks?symbols=<root>`: the contract with `isUS: true` of the entry whose `assetClass` is `STK`; several US entries → the one whose name matches `/iserver/secdef/search`'s first STK hit | Redis `mdh:ibkrweb:conid:stock:{root}`, 30 days |
| index | `/iserver/secdef/search?symbol=<root'>&secType=IND`, entry whose `description` matches the shared index exchange table, except Web `INDU` uses CME | Redis `mdh:ibkrweb:conid:index:{root}`, 30 days |
| future | `/trsrv/futures?symbols=<root>`, nearest effective last trade date ≥ today + 7 days (`ltd`, capped at `expirationDate` when present), exchange checked via contract info against the shared table (unknown root with several exchanges → `DATA_VALIDATION_ERROR` as `ibkr`) | Redis `mdh:ibkrweb:conid:future:{root}` until the roll cutoff |
| option | D10 | D10 |

Without Redis the in-process cache is used. `/iserver/secdef/search` for the root is always called once per process before strikes/info, as IBKR requires.

### D13: Configuration

`connection_config` (allowlist) for `ibkrweb`: `base_url`, `verify_tls`, `ca_bundle`, `account_id`, `compete`, `market_data_type`, `max_streams`, `login_url`. Environment defaults: `IBKRWEB_BASE_URL=https://127.0.0.1:5000`, `IBKRWEB_LOGIN_URL=` (browser-facing URL, needed under Compose where the browser cannot resolve `ibkr-cpgw`), `IBKRWEB_VERIFY_TLS=false`, `IBKRWEB_CA_BUNDLE=`, `IBKRWEB_ACCOUNT_ID=`, `IBKRWEB_COMPETE=false`, `IBKRWEB_MARKET_DATA_TYPE=3`, `IBKRWEB_MAX_STREAMS=80`, `IBKRWEB_TICKLE_INTERVAL_SECONDS=60`, `IBKRWEB_SESSION_INIT_TIMEOUT_SECONDS=15`, `IBKRWEB_PENALTY_SECONDS=900`, `IBKRWEB_SNAPSHOT_TIMEOUT_SECONDS=4`, `IBKRWEB_OPTION_SNAPSHOT_TIMEOUT_SECONDS=10`, `IBKRWEB_SNAPSHOT_BATCH_SIZE=50`, `IBKRWEB_IV_TIMEOUT_SECONDS=10`, `IBKRWEB_ALERT_WEBHOOK_URL=`. A changed `base_url`, `verify_tls` or `ca_bundle` closes the HTTP client and resets the session state.

### D14: Deployment of the gateway

The CPGW is not part of the MDH image. An optional compose profile `cpgw` builds `tools/cpgw/Dockerfile` (Eclipse Temurin 17 JRE, downloads `clientportal.gw.zip` from IBKR at build time, never pushed to a registry), mounts `tools/cpgw/conf.yaml` (`listenPort: 5000`, `ips.allow` with `127.0.0.1` and the compose network range) and publishes `127.0.0.1:5000:5000`. MDH reaches it as `https://ibkr-cpgw:5000`. The login is done from a browser on the host or through an SSH tunnel (`ssh -L 5000:127.0.0.1:5000 <server>`); the port is never exposed publicly. The README documents this, the daily login and the single-session rule.

### D15: Shared gateway with order-hub

order-hub (provider `ibkrweb`, change `add-ibkr-web-provider` in `../order-hub`) can use the same CPGW. One gateway holds one brokerage session for the username; MDH and order-hub both use it (no client ids, no competing sessions between them), and one daily login serves both. Consequences: the documented 10 requests/s limit and the penalty box apply to the gateway's IP as a whole, so MDH defaults to 6/s and order-hub to 2/s; a 429 seen by one service pauses only that service, the other one detects its own 429. Both services tickle (well below 1/s together) and both may run `ssodh/init` after a reset; the init is idempotent. `GET /iserver/marketdata/unsubscribeall` only affects market data streams, not orders. "Logout" in either admin UI ends the session for both; the logout dialog says so.

## Risks / Trade-offs

- [Daily manual login] → session panel, `login_required` state, metric and webhook; MDH answers fast with a clear error instead of timeouts. Unavoidable with the CPGW (IBKR does not support automated login).
- [Competing brokerage session with TWS/IBKR Mobile] → `compete = false` default, explicit `competing` state and admin warning; switching to `compete = true` is a conscious admin action.
- [Penalty box after a 429] → conservative limiter (6/s, history 50/min; 8/s together with order-hub), no retries on 429, 15-minute pause instead of hammering.
- [Cold option chains are slow] → conid cache in Redis; spike checks a one-request `secdef/info` path; chain requests inherit the existing response cache.
- [Undocumented snapshot details (string formats, batch size, volume field)] → spike records real responses; fixtures drive the parser tests.
- [No IV history, no news, no continuous futures] → declared gaps with 501 or documented deviation; `ibkr` remains available for these.
- [Self-signed TLS] → `verify_tls = false` only accepted for loopback hosts and the compose service name; for any other host the admin must provide `ca_bundle` or enable verification (validation error otherwise).

## Migration Plan

1. Deploy with `ibkrweb` disabled; nothing changes for existing clients.
2. Start the CPGW (profile `cpgw` or own installation), log in, enable `ibkrweb`, run the connection test and the parity check (task 6.3).
3. Switch the system defaults (prices, options, companies, volatility) from `ibkr` to `ibkrweb` when desired; keep `ibkr` enabled only with a second username, otherwise disable it.
4. Rollback: set the defaults back to `ibkr` and disable `ibkrweb`.

## Live spike results (localhost paper gateway)

- Authenticated status worked with `GET` and with `POST` carrying JSON `{}`; a bodyless `POST` produced an HTML bad request. `ssodh/init` with `compete: false`, `accounts`, `tickle` and SSO validation worked. Tickle embeds status in `iserver.authStatus` and reports a relative `ssoExpires` in milliseconds.
- `/trsrv/stocks` resolved AAPL (`265598`), SPY (`756733`) and `BRK B` (`72063691`). `BRK.B` and the test unknown symbol returned empty lists. Use the space-separated form when sending the share class to the gateway.
- Index search resolved SPX (`416904`, CBOE), NDX (`416843`, NASDAQ), VIX (`13455763`, CBOE) and INDU (`1935181`, **CME**). `DJI` returned `No symbol found`. Use a Web-specific INDU exchange override, preserving the TWS NYSE mapping. The INDU snapshot had availability `N` for this login.
- Futures lists provided no `exchange`; `/iserver/contract/{conid}/info` confirmed CME/`ESZ6` and NYMEX/`CLZ6`. CL exposed `ltd=20261201` but `expirationDate=20261120` (confirmed as `maturity_date` in contract info). A Web future must also pass the seven-day buffer against its displayed expiry when that date precedes `ltd`; otherwise an about-to-expire contract could qualify.
- AAPL pre-flight returned only identifiers; repeated snapshots delivered values. `6509` examples included `DB` (AAPL and futures), `Z` (SPX, NDX), `ZBd` (AAPL options) and `N` (INDU). AAPL `87="39.9M"` vs. `7762="39872336"`, option open interest `7638="27.6K"`, and strike IV plus Greeks were observed. Batches of 50 and 51 returned the requested number of distinct conids; keep 50 as the conservative default. No halted/close prefixes were observed; handle the documented formats.
- AAPL history returned `1min`, `2min`, `1h`, `1d` and `1w`; `outsideRth=true` 1-minute queries hit 1,000 bars. Use `len(data)`, not `points`, which was one less than the list length. History returned `mdAvailability="S"` even on valid data; do not apply the snapshot availability allowlist to this marker. Daily bars started at the opening (14:30 UTC regular / 09:00 UTC extended in the sample); use exchange-local date at midnight to match TWS daily `PriceBar` serialization, which is timezone-naive. Weekly sample timestamps were Monday midnight UTC; keep their date instead of shifting to Sunday via New York. History volume was scaled (`volumeFactor=40`, AAPL); multiply `v` by the factor before integer conversion. Trading schedule returned `schedules` keyed by `YYYYMMDD`, and `opening`/`closing` in **seconds**, not milliseconds.
- `secdef/info` needed `strike`, returned both rights without a `right` filter, and included several maturities per strike/right (weekly and monthly). Single-strike calls in the sample took 0.29–0.54 seconds.
- `secdef/search?symbol=apple&name=true` returned `secType="STK"` at the top level, empty `sections` and `companyHeader="APPLE INC (NASDAQ)"`; the name and listing exchange were not populated separately. Normal symbol/option lookup still uses the `sections` shape.
- Accepted conservative history window pairs (`bar`, `period`): `1min/12h`, `2min/1d`, `5min/3d`, `15min/1w`, `30min/2w`, `1h/1m`, `1d/2y`, `1w/10y`. Weekend queries returned prior sessions. Backward pages overlap because the gateway treats `startTime` as exclusive and can omit the immediately adjacent minute; the provider de-duplicates by timestamp.
- `7283` returned percentages for AAPL (`23.601%`), SPY (`22.677%`), SPX (`22.964%`), NDX, VIX and ES (`10.781%`); CL and INDU had `N/A`. Include stock, ETF, index and future in `volatility_sec_types` under D11; a missing value for an individual contract remains an explicit error.
- Both attempted IV history source names returned HTTP 200 with **price candles**, not IV, for AAPL, SPY and SPX. The data matched `source=Last`. Keep `volatility_history_sec_types` empty and return 501 without a gateway request.
- The destructive `/logout` check was deferred to keep the user’s session active. Exact snapshot hard limit beyond 51 and live examples of `C`/`H` prefixes were not established.
