## 1. Gateway spike

- [x] 1.1 Against a live CPGW session, record `secdef/search` for `ES` and `CL`, `secdef/strikes` with `sectype=FOP` (month code, required `exchange`), and `secdef/info` for one strike each. Store the payloads, scrubbed of account data, as test fixtures.
- [x] 1.2 Determine how a FOP contract exposes its underlying future (field in `secdef/info` vs. `/iserver/contract/{conid}/info`) and how the regular expiry and trading class are flagged; record the answer in design.md Open Questions.

## 2. Contract and model

- [x] 2.1 Add optional `underlying_contract`, `underlying_price`, `multiplier`, `trading_class` and `exchange` to `OptionChain`, including the CSV columns; existing chain tests stay green.
- [x] 2.2 Allow `future` for the option-chain endpoint in the per-endpoint namespace support set; the option quote endpoint keeps rejecting it. Add tests for both.
- [x] 2.3 Add the optional `trading_class` query parameter to `GET /options/{symbol}/chain` and the MCP option-chain tool; ignore it for non-futures underlyings.
- [x] 2.4 Verify that providers without `future` in `option_underlying_sec_types` answer 501 `CAPABILITY_NOT_SUPPORTED` (schwab, polygon).

## 3. ibkrweb futures-option chains

- [x] 3.1 Resolve the FOP search row for verified roots `ES` and `CL`: exact symbol, `FOP` section and exchange from `FUTURES_EXCHANGES`. Reject other roots before contacting IBKR.
- [x] 3.2 Query listed buckets (`ES`: expiry month; `CL`: expiry and following month) with serial one-sided `secdef/info` requests. Collect classes by exact expiry before filtering strikes and rights; use contract info for surviving conids only.
- [x] 3.3 Implement trading-class selection (explicit, verified standard `ES`/`LO`, then single class, else 422 with `details.trading_classes`); an unknown explicit class yields an empty chain.
- [x] 3.4 Cache FOP conids and native identifiers under `mdh:ibkrweb:fopconid:{root}:{class}:{yyyymmdd}:{C|P}:{strike}` until the day after expiry. Cache month listings including absences, without sharing equity option keys.
- [x] 3.5 Snapshot options and the underlying future together within the existing budget; map `underlying_contract`, `underlying_price`, `multiplier`, `trading_class` and `exchange`; `symbol` is the IBKR local symbol.
- [x] 3.6 Report entitlement denials with `sec_type` `future`; declare `future` in `ibkrweb.option_underlying_sec_types`.

## 4. ibkr (TWS) futures-option chains

- [x] 4.1 Share checked root/exchange lookup, trading-class selection and chain-metadata mapping between `ibkrweb` and `ibkr`.
- [x] 4.2 In `ibkr.py`, branch verified roots to `reqContractDetails(FuturesOption(root, YYYYMMDD, exchange))` with the exchange from `FUTURES_EXCHANGES`; never build `Option(…, "SMART")` for futures.
- [x] 4.3 Apply class selection and strike filter, take `multiplier`, exchange and `underConId`, snapshot options and the underlying future via `_get_tickers_snapshot`, and map `localSymbol` to `symbol`.
- [x] 4.4 Declare `future` in `ibkr.option_underlying_sec_types`; verify with mocked `ib_async` contract details for ES and CL (standard class, weekly override, underlying), plus the connection-error path.
- [x] 4.5 Once TWS is online: live parity check, with the same `F:ES` and `F:CL` chains from `ibkr` and `ibkrweb` matching in strikes, class, multiplier and underlying.
  - Live parity on 2026-11-24 (ibeam Web gateway, then IB Gateway paper via TWS API on port 4002, run one after the other because both share the account). `F:ES` 2027-03-19 (strikes 7200–7450): 12 of 12 options identical in strike, right and local symbol (`ESH7 C7200` …); `trading_class` `ES`, `multiplier` 50, `exchange` `CME`, underlying `ESH7` equal; underlying price 7349.75 on both. `F:CL` 2026-12-16 (strikes 70–90): 82 of 82 options identical; `trading_class` `LO`, `multiplier` 1000, `exchange` `NYMEX`, underlying `CLF7` equal; underlying price 79.67 (Web) vs 79.71 (TWS), a delayed-tick difference.
  - The earlier refusal on `127.0.0.1:4001` was a port issue, not an outage: the Kubernetes service maps 4001 to the live API (no listener for a paper login) and 4002 to the paper API. Cold first TWS request took about 11 s (ES) and 19 s (CL), warm about 4.5 s, so the default 10 s provider timeout can trigger `PROVIDER_TIMEOUT` on the first call.

## 5. Tests and docs

- [x] 5.1 Unit tests with the spike fixtures: ES weekly, CL default/weekly (different underlying futures), ES quarterly-versus-weekly class choice, ambiguity, empty strikes and expiries, a warm chain without `secdef/info`, stock `CL` and `F:CL` cache separation.
- [x] 5.2 Route tests: `F:ES` chain via `ibkrweb` and `ibkr`, 501 for Schwab and Polygon, 422 for the futures option quote, `trading_class` passthrough and case-insensitive cache separation.
- [x] 5.3 Update the OpenAPI description of the chain endpoint, README (supported roots and providers, delayed data note), and CHANGELOG; bump the minor version to 1.9.0.
- [x] 5.4 Run ruff, `mypy --strict app/` and the full CI unit suite; smoke-test `F:ES` and `F:CL` against the live paper Client Portal Gateway.
  - Ruff, strict mypy, strict OpenSpec validation and OpenAPI 1.9.0 passed. The CI unit suite reported 1,383 passed and 1 skipped (84% coverage).
  - Live Web smoke on 2026-11-23: ES `EW4` → `ESZ6`, quarterly `ES` → `ESZ6`, weekly `EW3` → `ESH7`; CL `LO` → `CLF7`, weekly `WL3` → `CLG7`. Each request returned both sides at the checked strike and an underlying price.
