## ADDED Requirements

### Requirement: Futures option chains over the Web API
`ibkrweb` SHALL declare `future` in `option_underlying_sec_types`. For a futures root, `get_option_chain` SHALL:
1. resolve the root's underlying via `/iserver/secdef/search` (row whose `symbol` equals the root and whose sections contain `FOP`, restricted to the exchange from the shared futures exchange table when the root is listed there);
2. inspect the listing bucket of the expiry month for `ES`, and the expiry month and following month for `CL`, using only buckets present in the `FOP` section;
3. load and cache the month definitions via `GET /iserver/secdef/info?conid&sectype=FOP&month=<MMMYY>&exchange=<exchange>&right=<C|P>`, making one side per request serially. Discover classes by exact `maturityDate` across those buckets before filtering strikes and rights;
4. retain only the selected trading class (capability `futures-option-chains`), apply the strike and side filters, then look up the surviving native option symbols and underlying conids via `/iserver/contract/{conid}/info`.

The contract details SHALL provide `multiplier`, `tradingClass`, the listing exchange and the underlying futures contract. The underlying contract's price SHALL be requested in the same snapshot batch as the options. Option snapshots SHALL use the same fields, timeout and mapping as equity option chains, except that `symbol` SHALL be the IBKR local symbol. Entitlement denials SHALL be reported with `sec_type` `future`. Futures-option conids SHALL be cached until the day after expiry under `mdh:ibkrweb:fopconid:{root}:{trading_class}:{yyyymmdd}:{C|P}:{strike}`. These keys SHALL be separate from the equity `optconid` keys, so an equity and a futures root with the same name never collide.

#### Scenario: ES chain with Greeks
- **WHEN** `GET /options/F:ES/chain?provider=ibkrweb&expiry=2026-11-27&min_strike=7200&max_strike=7300` is requested with delayed data
- **THEN** the result contains calls and puts with bid/ask, IV as decimal fraction, Greeks and open interest, `multiplier` `50`, `exchange` `CME`, and `underlying_contract` and `underlying_price` of the December 2026 ES future

#### Scenario: Equity and futures root with the same name
- **WHEN** chains for the stock `CL` (Colgate-Palmolive) and for `F:CL` are requested on the same expiry
- **THEN** each chain is resolved through its own secdef flow and cache keys, and neither contains contracts of the other

#### Scenario: Warm futures chain
- **WHEN** the same futures chain is requested again
- **THEN** while the listing and contract metadata caches are warm, no `secdef/info` requests are sent, only snapshots for the options and the underlying future

#### Scenario: Missing futures entitlement
- **WHEN** the gateway denies market data for the futures options
- **THEN** the request fails with the existing entitlement error mapping and `sec_type` `future`
