## Context

- **Current state:** MDH serves option chains for `stock`, `etf` and `index` underlyings. Futures (`F:<ROOT>`) are supported for prices and volatility with front-month semantics. `ibkrweb` resolves equity chains through `/iserver/secdef/search` → `/secdef/strikes` (`sectype=OPT`) → `/secdef/info`, caches conids in Redis and maps snapshots into `OptionQuote`. Futures contracts are already resolved through `/trsrv/futures` and the shared `FUTURES_EXCHANGES` table.
- **Upstream check (2026-11-23):** the connected IBKR account was checked through the IBKR connector, with the same account and the same secdef model as the Web API:
  - `ES` (CME) lists `FOP` with daily, weekly, monthly and quarterly expiries and several trading classes per date (`ES`, `EW`, `EW1`–`EW4`, `E1A`…`E5B`), multiplier 50.
  - `CL` (NYMEX) lists `LO` monthly and several weekly classes. The regular `LO` options expiring 2026-12-16 are written on the January 2027 future, multiplier 1000.
  - Snapshots return delayed bid/ask, last, IV, Greeks and open interest.
- **Stakeholders:** VisioTrade, which wants futures-option analytics (GEX, IV, candidates) from a Schwab futures watchlist.

## Goals / Non-Goals

**Goals:**
- Futures-option chains via `ibkrweb` and TWS `ibkr` with identical results, behind the existing chain endpoint and response model.
- Enough metadata for correct analytics: underlying contract and price, multiplier, trading class, exchange.
- A deterministic class choice, with an explicit override and an explicit error on real ambiguity.

**Non-Goals:**
- Futures-option quotes (`/options/F:…/quote/…`) and an expirations or trading-class discovery endpoint.
- Schwab and Polygon. They keep 501 for `future`; adding them later only extends their support set.
- Index option chains for the IBKR providers. They still declare only `stock` and `etf`; that is a separate change.
- Contract-month symbols in the namespace (`F:ESZ26`). Chains are keyed by root and expiry.
- Real-time entitlements. That is account configuration, not code.

## Decisions

1. **Root plus expiry, not contract month, identifies a futures chain.**
   - **Why:** the option expiry, not the future, is what consumers choose (DTE targeting), and the same option date can sit on a later contract (CL). `F:<ROOT>` already exists, so the namespace stays unchanged.
   - **Rejected alternative:** `F:ESZ26` as underlying. It forces clients to know the exchange's option-to-future mapping and does not fix the CL case.
2. **The underlying comes from the provider's contract details, never from date arithmetic.**
   - **Approach:** retrieve `underlying_con_id` and the native option symbol from `/iserver/contract/{option_conid}/info`. MDH requests that future conid's snapshot in the same batch as the options and gets its local symbol from its own contract info.
   - **Rejected alternative:** computing the underlying from exchange calendars per root. It is brittle and different for every product.
3. **Trading class: override, then regular, then the single class, else 422.**
   - **Why:** IBKR does not expose an explicit standard flag. Use the verified product codes `ES` and `LO` when present on that date. Different classes can use different underlyings, so mixing them would corrupt GEX and IV. Return 422 with `details.trading_classes` when neither a regular nor sole class can be selected.
   - **Rejected alternatives:** merging all classes, or picking by volume (non-deterministic).
4. **Metadata lives at chain level, as optional fields.**
   - **Why:** one class per chain means one multiplier and one underlying. Optional fields keep the equity schema and existing clients valid; CSV repeats them per row.
5. **Separate cache namespace `fopconid` that includes the trading class.**
   - **Why:** equity and futures roots share names (`CL` stock vs. `F:CL`), and different classes share dates and strikes.
6. **TWS: one `FuturesOption` contract-details request per expiry.**
   - **Approach:** `reqContractDetails(FuturesOption(root, YYYYMMDD, exchange=…))` returns every contract expiring that day, with `tradingClass`, `multiplier` and `underConId`. Class selection, strike filtering and the underlying come straight from that one response; snapshots reuse `_get_tickers_snapshot`.
   - **Rejected alternatives:** `reqSecDefOptParams` (it needs the underlying future conid up front, which is exactly what the CL case does not give us) and the existing equity path that builds `Option(…, "SMART")` (futures options are not SMART-routed).
   - **Shared logic:** trading-class selection and the metadata mapping live in one provider-independent helper used by `ibkr` and `ibkrweb`, so both behave the same.
7. **Same snapshot mapping and budget as equity chains.**
   - **Approach:** reuse the field list, timeout and 50 % completion rule. The extra underlying conid counts against the existing snapshot stream budget.
8. **Start with the live-verified roots ES and CL.**
   - **Approach:** use the exchange table for both transports. The Web API checks the expiry-month listing bucket for ES and the expiry-month and following-month buckets for CL. This is not an underlying selection rule. Other roots return 501 with the supported roots; each new root needs verified bucket and standard-series rules before it is enabled.
9. **Resolve available classes before applying the request's strike window.**
   - **Approach:** use `secdef/info` without `strike`, one side at a time. The observed two-sided ES response and parallel CL requests could return malformed JSON; serial single-side requests worked. Cache compact month listings (including absent strikes and maturities) for one hour. Look up native symbols and underlying IDs only for matching options, using the expiry-bound `fopconid` cache.

## Risks / Trade-offs

- **[Risk]** The `secdef/strikes` and `secdef/info` parameters for `FOP` (month code semantics, required `exchange`, underlying conid field) may differ from what the connector shows. → Task 1 is a gateway spike that records real payloads as fixtures before implementation.
- **[Risk]** ES month definitions contain thousands of options, so cold chains can be slow. → Fetch each listed bucket at most once per side while the month cache is warm. Apply filters before the paced per-option detail lookups; cache their result until after expiry.
- **[Risk]** IBKR may mark no class as regular on a date that carries only weeklies. → Rule 3 takes the single class; otherwise 422 with the class list, never a guess.
- **[Risk]** TWS is currently offline, so the `ibkr` path cannot be verified live during implementation. → Build it against mocked `ib_async` contract details that mirror the spike payloads; the live parity check (task 4.5) stays open until TWS is reachable.
- **[Trade-off]** Both providers depend on IBKR. If the account or its entitlements fail, there are no futures chains. → This is accepted; the support-set mechanism allows adding other providers later.
- **[Risk]** Delayed data only. → Responses keep reporting the market data type; entitlement denials use the existing error mapping.

## Migration Plan

The change is additive. Deploy MDH with the new support set and fields, then bump the OpenAPI minor version. Rollback means redeploying the previous version. Cached `fopconid` keys are harmless and expire on their own. VisioTrade adopts the change in a separate change after this one ships.

## Open Questions

- **Answered by the live paper gateway spike (2026-11-23):** `secdef/search` returns separate exact-symbol rows for FOP and stock; the listing exchange is in the `FOP` section. Omitting `exchange` from the CL `secdef/strikes` request returned empty call and put lists. `secdef/info` provides `tradingClass`, `maturityDate`, `multiplier` and `exchange`, but neither the native local symbol nor the underlying conid. Fetch `/iserver/contract/{option_conid}/info` for `local_symbol` and `underlying_con_id`, then `/iserver/contract/{underlying_con_id}/info` for the future's `local_symbol`. Trimmed captures without account/session payloads: `tests/fixtures/ibkrweb/futures_option_secdef.json`.
- **Design issue exposed by the spike:** `month` is a listing bucket, not necessarily the calendar month of `maturityDate` or the underlying future. Querying only the expiry month silently returns the wrong class and underlying for the CL example:

  | Root | Expiry | `month` | Class | Underlying | Multiplier |
  | --- | --- | --- | --- | --- | --- |
  | ES | 2026-11-27 | `NOV26` | `EW4` (weekly) | `ESZ6` | 50 |
  | ES | 2026-12-18 | `DEC26` | `ES` (quarterly) | `ESZ6` | 50 |
  | ES | 2026-12-18 | `DEC26` | `EW3` (weekly) | `ESH7` | 50 |
  | CL | 2026-12-16 | `DEC26` | `WL3` (weekly) | `CLG7` | 1000 |
  | CL | 2026-12-16 | `JAN27` | `LO` (regular) | `CLF7` | 1000 |
  | CL | 2027-01-14 | `FEB27` | `LO` (regular) | `CLG7` | 1000 |

- **Regular class identification:** Neither Web API detail response exposed an explicit regular-expiry flag for the sampled contracts. A description without a class prefix happens to identify quarterly ES, but both `LO` and `WL3` have prefixes, and neither equals the root `CL`. Decisions 8–9 record the resulting scope and discovery approach.
- Should a later change add `GET /options/F:<ROOT>/expirations`, listing dates and trading classes, so clients can discover classes without a 422 round trip?
