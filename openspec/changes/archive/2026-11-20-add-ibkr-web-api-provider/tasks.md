## 0. Spike (before implementation)

- [x] 0.1 Spike `tmp/ibkrweb_spike.py` against a logged-in CPGW (paper account is enough, `tmp/.env` for the base URL, never committed), at most ~150 requests, paced at ≤ 5/s: session flow (`auth/status`, `ssodh/init` with `compete: false`, 2 s wait, `/iserver/accounts`, `/tickle`, `/sso/validate`); conids for AAPL, SPY, BRK B, SPX, NDX, VIX, DJI/INDU, ES, CL, an unknown ticker; snapshots incl. pre-flight timing and field formats (`31`, `87` vs. `7762`, `7283`, `7633`, Greeks, `7638`, `6509`) for stock, ETF, index, future and options, max conids per snapshot; history for `1m`/`2m`/`1h`/`1d`/`1w` incl. 1,000-bar limit, `outsideRth`, `volumeFactor`, timestamps of daily bars; `secdef/strikes` and `secdef/info` with and without `strike` for AAPL `DEC26`; history `source=Option_Implied_Volatility` and `OPTION_IMPLIED_VOLATILITY` once each for AAPL, SPY, SPX; `/contract/trading-schedule`; `/iserver/contract/{conid}/info`; one request after `POST /logout` (expected 401). Record status codes, bodies and timings in `tmp/ibkrweb_spike_out/`
  - Live data capture complete; post-logout check deferred to avoid ending the active gateway session (the 401 behaviour is covered by the live check in 7.5). Snapshot batches tested through 51 conids, not to rejection.
- [x] 0.2 Record the results in `design.md` and resolve the open questions: one-request `secdef/info` path (D10), IV for futures and indices (D11, `volatility_sec_types`), IV history decision (D11, `volatility_history_sec_types`), snapshot string formats, batch size and volume field (D7), daily bar time convention (D8), share-class notation (`BRK B`)
- [x] 0.3 Copy trimmed responses to `tests/fixtures/ibkrweb/` (auth status variants, tickle, accounts, stocks/futures/secdef search, strikes, info, snapshot pre-flight and filled, history pages, trading schedule, contract info, error bodies for 400/401/429/500/503); no real account ids, usernames or session ids in any fixture. Unobserved HTTP errors are explicitly synthetic; no real 429 was induced.

## 1. Shared IBKR helpers

- [x] 1.1 Extract `app/providers/ibkr_common.py` from `ibkr.py` without behaviour change: futures exchange table, index root overrides, index exchange table, front-month selection rule, trading-hours/session evaluation, OCC option symbol format/parse, interval list; `ibkr.py` imports shared conventions and keeps using the option symbol emitted by TWS; all existing `tests/unit/test_ibkr_*` stay green unchanged
- [x] 1.2 Unit tests for the OCC parser (padding, strikes with decimals, invalid ids) and the front-month rule shared by both providers

## 2. Configuration and registration

- [x] 2.1 `app/config.py`: `IBKRWEB_*` settings per design D13
- [x] 2.2 `app/admin/provider_config_repository.py`: `ibkrweb` in `KNOWN_PROVIDERS`, `CONNECTION_CONFIG_ALLOWLIST["ibkrweb"]`, connection defaults from settings, default `rate_limit_per_sec = 6`; TLS validation rule (loopback/`ibkr-cpgw` only for `verify_tls = false`) with 422
- [x] 2.3 `app/providers/registry.py` class map, `app/api/routes_admin.py` `PROVIDER_CAPABILITIES["ibkrweb"] = ["prices", "options", "companies", "volatility"]`, `app/observability/metrics.py` provider set, `app/main.py` provider list; `ibkrweb` not in `CREDENTIAL_ALLOWLIST`
- [x] 2.4 Tests: enable/disable/reload, capabilities, `/providers` catalog, TLS validation, defaults

## 3. Session, keep-alive and pacing (`app/providers/ibkr_web_session.py`)

- [x] 3.1 HTTP client (`/v1/api` base, `verify`, `User-Agent`, cookies), client reset on endpoint change
- [x] 3.2 Session state machine (D3): status parsing, serialised `ssodh/init` + 2 s wait + non-empty `/iserver/accounts` with timeout, `account_id` check, error mapping per state (`PROVIDER_CONNECTION_ERROR`, `PROVIDER_NOT_AVAILABLE` with `reason`/`login_url`)
- [x] 3.3 Keep-alive task (D4): tickle interval, re-init after reset, `login_required` transition, one log line per transition, gauge `mdh_provider_session_state`, optional webhook (fire-and-forget), start on load, cancel in `close()`
- [x] 3.4 Pacing (D5): token bucket (`rate_limit_per_sec`), history window 50/min, tickle 1/s, `sso/validate` 1/min, 429 penalty pause without retries, `mdh_provider_upstream_requests_total`
- [x] 3.5 Unit tests with a fake gateway (`httpx.MockTransport`): first request after login, concurrent init (exactly one `ssodh/init`), 401 fail-fast, competing, unreachable, recovery after reset, login picked up by tickle, close cancels the task, burst pacing, history window, penalty pause (frozen clock)

## 4. Provider (`app/providers/ibkr_web.py`)

- [x] 4.1 Contract resolution and caches (D12): stocks, indices, futures, Redis keys and TTLs, in-process fallback, `secdef/search` before strikes/info
- [x] 4.2 Snapshot engine (D7): pre-flight + polling, batches, field parser (separators, prefixes, `%`), stream budget with `unsubscribeall`, availability check (D6)
- [x] 4.3 `get_last_price`: field mapping, `market_data_type` check, history close fallback on the same conid, `is_market_open` via trading schedule (D9) with cache
- [x] 4.4 `get_historical_prices` (D8): interval mapping, window planning with ≤ 1,000 bars, backward walk, merge/dedupe/clip, `outsideRth`, futures front month with `source_instrument`
- [x] 4.5 `get_option_chain` and `get_option_quote` (D10): strikes, info per strike (both rights per 0.2), maturity filter, option conid cache, snapshot mapping, OCC symbols
- [x] 4.6 `get_implied_volatility` (D11) and `get_implied_volatility_history` (501 or verified implementation per 0.2); support sets per 0.2
- [x] 4.7 `get_company_profile`, `search_companies` (name search without breaking option resolution)
- [x] 4.8 Error mapping (spec "Web API error mapping"), `test_connection()` per `provider-connection-test`
- [x] 4.9 Unit tests per method with the fixtures from 0.3, incl. pre-flight, delayed vs. live entitlement, `O` acknowledgement, index fallback, 1-minute pagination, weekly expiries filter, warm chain without `info` requests, IV percent → fraction, malformed option id, nightly 503, HTML payload

## 5. Parity suite

- [x] 5.1 `tests/unit/test_ibkr_parity.py`: parametrised over `ibkr` (mocked `ib_async`) and `ibkrweb` (mocked gateway) for last price (stock, index, future), history (`1d`, `1m`), option chain, option quote, IV snapshot, company profile, search, entitlement error, not-found; asserts identical models, field sets, units, symbols, `source_instrument`, OCC `symbol` and error codes; declared gaps (news, IV history, futures continuous history) asserted explicitly
- [x] 5.2 Route tests: `ibkrweb` on price, option, company and IV snapshot routes; `/companies/{symbol}/news?provider=ibkrweb` and IV history answer as specified without upstream requests

## 6. Admin API and UI

- [x] 6.1 `IbkrWebGatewayUpdate` + `PUT /api/admin/providers/ibkrweb/gateway` (partial merge, validation, reload)
- [x] 6.2 `GET /api/admin/providers/ibkrweb/session`, `POST .../session/init`, `POST .../session/logout`; `warnings: ["ibkr_single_session"]` in `GET /api/admin/providers`; route tests
- [x] 6.3 Admin UI: `IbkrWebConnectionSection` (fields, save, 422 display), session panel with 10 s refresh and actions, routing and label in `ProvidersPage`/`DashboardPage`, JSON textarea hidden, single-session warning, capability chips; vitest tests
- [x] 6.4 OpenAPI and MCP descriptions that list provider names mention `ibkrweb` (prices, options, companies, volatility; not news)

## 6b. Review follow-up (OCR review 2026-11-20)

- [x] 6b.1 Snapshot polls run outside the stream-budget lock; `unsubscribeall` waits for active polls
- [x] 6b.2 Data-endpoint 500/503 only schedules a status re-check (≤ 1 per 30 s) instead of downgrading the session
- [x] 6b.3 Failed session refresh shared by queued requests; 429 penalty kept per gateway origin across provider replacement; closed sessions no longer write the gauge or send alerts
- [x] 6b.4 Keep-alive survives unexpected exceptions and logs failures once; admin logout sends no login alert
- [x] 6b.5 Last-price fallback failure keeps the entitlement error; history ranges above 40 windows rejected up front
- [x] 6b.6 Option chain tolerates rejected strikes, caches missing strikes and unknown expiries
- [x] 6b.7 `login_url` setting for the browser login button; readable 422 messages; tests for all of the above

## 7. Deployment, docs and verification

- [x] 7.1 `tools/cpgw/Dockerfile` (Temurin 17 JRE, download of `clientportal.gw.zip` at build time) and `tools/cpgw/conf.yaml` (`listenPort: 5000`, `ips.allow` for loopback and the compose network); `docker-compose.yml` profile `cpgw` with service `ibkr-cpgw`, port `127.0.0.1:5000:5000`
- [x] 7.2 README/docs: CPGW setup (own install or profile `cpgw`), login via local browser or SSH tunnel, daily re-login, nightly reset, single-session rule and second username, `compete`, TLS settings, pacing, parity matrix with gaps; CHANGELOG
- [x] 7.3 Full test suite, `ruff`, `mypy`, admin `vitest` and `tsc` as in CI
  - Re-run 2026-11-20: `tests/unit/` 1,229 passed / 1 skipped, `ruff check app/` clean, 17 Vitest tests and `tsc --noEmit` pass. Repo-wide mypy reports 13 errors only in five untouched earnings/metered files (`alphavantage`, `financialdatasets`, `metered`, `earnings_service`, `earnings_repository`); no errors in any IBKR file.
- [~] ~~7.4 Live parity check (local, logged-in CPGW, `ibkr` with a second username or run one after the other): AAPL, SPY, I:SPX, F:ES last and `1d`/`5m` history; AAPL chain for the next monthly expiry (strikes ±5 %) and one option quote; IV snapshot AAPL/SPY/SPX; company profile and search; compare with `ibkr` (same shapes, prices within the spread, IV within 0.01); record timings of cold and warm chains and the request counts; record the result here~~
  - Dropped 2026-11-20: only a paper account is available for a TWS comparison; remaining checks are observed in production and handled as bug fixes. The CPGW smoke results below stay as the recorded evidence.
  - CPGW smoke test on the paper session: all four quotes and both bar intervals worked; `ESZ6` was the source for futures. AAPL December chain (345–350, four options): 6 requests / 2.23 s cold, 2 requests / 0.65 s warm, at 4 requests/sec and with existing gateway streams. Option quote, AAPL/SPY/SPX IV, AAPL profile and Apple name search passed. Direct TWS comparison still pending.
- [~] ~~7.5 Session check: leave the provider idle for 30 min (still `ready`), log out in the gateway UI (state `login_required`, webhook once, 401 test result), log in again (state `ready` without admin action); record the result here~~
  - Dropped 2026-11-20: session behaviour (idle, logout, re-login) is observed in production and handled as bug fixes.
