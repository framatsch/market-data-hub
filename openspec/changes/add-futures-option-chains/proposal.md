## Why

Consumers such as VisioTrade want to analyse options on futures (`/ES`, `/NQ`, `/CL`, `/GC`, …) the same way as equity and index options. MDH already serves futures prices (`F:ES`), but `GET /options/F:ES/chain` is rejected with HTTP 422 because the option-chain endpoint only accepts `stock`, `etf` and `index` underlyings. Schwab's Trader API offers no futures-option chains, but IBKR does. A check against the connected IBKR account on 2026-11-23 confirmed delayed bid/ask, IV, Greeks and open interest for ES (CME, multiplier 50) and CL (NYMEX, multiplier 1000) futures options. The gap is in the hub, not in the upstream data.

## What Changes

- The option-chain endpoint accepts `future` underlyings (`F:<ROOT>`); the option quote endpoint does not yet.
- `ibkrweb` (Client Portal Web API, `sectype=FOP`) and `ibkr` (TWS API, `FuturesOption` contract details) implement futures-option chains and declare `future` in `option_underlying_sec_types`. The first release supports the verified roots `ES` and `CL`; other roots and providers answer 501 `CAPABILITY_NOT_SUPPORTED`.
- For a futures root, the option expiry selects the underlying contract. `F:<ROOT>` keeps its front-month meaning for prices, but for chains the underlying is the contract the requested options are written on (e.g. 2026-12-16 `CL` options sit on the January 2027 future).
- A new optional query parameter `trading_class` chooses between several option classes listed on the same date (e.g. `ES` quarterly vs. `EW3` weekly on 2026-12-18). Without it, a deterministic default applies; an ambiguous date fails with 422 and lists the available classes.
- `OptionChain` gains optional fields: `underlying_contract`, `underlying_price`, `multiplier`, `trading_class` and `exchange`. They are filled for futures chains and stay `null` where a provider does not supply them. The change is additive and non-breaking.
- Futures-option conids are cached under their own key namespace, including the trading class.

## Capabilities

### New Capabilities
- `futures-option-chains`: API contract for option chains on futures underlyings. Covers underlying contract selection by expiry, trading-class selection, chain metadata fields (contract, underlying price, multiplier, class, exchange) and error behaviour. Also covers the TWS `ibkr` implementation, which has no provider spec of its own.

### Modified Capabilities
- `symbol-namespaces`: the option chain endpoint additionally accepts `future` underlyings (per-endpoint namespace support).
- `ibkr-web-provider`: new requirement for futures-option chains over the Web API (FOP secdef flow, snapshot mapping, caching, entitlement mapping).
- `provider-symbol-mapping`: futures front-month semantics clarified: they do not apply to option chains, where the expiry determines the underlying contract.

## Impact

- **API**: `GET /options/{symbol}/chain` accepts `F:<ROOT>` and the new `trading_class` parameter; `OptionChain` gains five optional fields (JSON and CSV). OpenAPI version bump (minor).
- **Code**: `app/utils/symbols.py` (endpoint support set), `app/models/options.py`, options route/service, `app/providers/ibkr_web.py`, `app/providers/ibkr_web_contracts.py`, `app/providers/ibkr.py`, MCP option-chain tool schema, tests.
- **Providers**: `ibkrweb` and `ibkr` (TWS). `schwab` and `polygon` are unchanged and keep 501 for `future`. TWS is currently offline, so the `ibkr` path is built against mocked `ib_insync` responses, and its live check follows once TWS is back.
- **Consumers**: VisioTrade stores Schwab watchlist futures as `F:ESZ26`. It must request chains with the root (`F:ES`) plus expiry, and it must use `multiplier` and `underlying_price` instead of assuming 100 and a spot price. That is a separate VisioTrade change.
- **Market data**: with the current subscription, futures-option data is `DELAYED`. Real-time needs CME/NYMEX/COMEX/CBOT entitlements at IBKR; denials map to the existing entitlement errors.
