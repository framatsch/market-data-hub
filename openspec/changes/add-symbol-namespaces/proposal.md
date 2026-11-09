## Why

A bare ticker does not say what kind of instrument it is: `ES` is both the Eversource stock and the S&P 500 E-mini future. Today clients must pass a separate `sec_type` parameter, and its handling is inconsistent:
- Allowed values, defaults (`stock` vs `STK`) and case handling differ between REST, MCP, services and providers. Symbols are upper-cased in about 20 places. Common notations like `^SPX` are partly stripped, and `/ES` breaks REST routing.
- Only IBKR (prices) and LSEG/IBKR (volatility) act on `sec_type` at all. Polygon, Schwab, Prixe and LSEG prices silently treat an index or future as a stock ticker.
- Missing market-data subscriptions surface differently per provider: a silent fallback, `PROVIDER_NOT_AVAILABLE` (503), or an IBKR 503. Clients cannot tell "not subscribed" from "provider down".

The goal is that one symbol notation works the same way against every provider. Each provider translates it into its native identifier. Anything the hub cannot translate, or the user's subscription does not cover, is reported with a clear, uniform error.

## What Changes

- Introduce a namespaced symbol notation `[<NS>:]<ROOT>`:
  - `F:ES` is a future.
  - `I:SPX` is an index.
  - `O:<OCC>` is an option contract.
  - A bare `AAPL` is a stock or ETF.
  - Aliases `^SPX` (index) and `/ES` (future) are accepted where the transport allows them.
  - Provider-native notations (`.SPX`, `$SPX`, `ESc1`) are rejected with a hint to use the canonical form.
- Add one central parser (`app/utils/symbols.py`) that returns a canonical `ParsedSymbol`. Every REST route, MCP tool, WebSocket subscription and cache key builder uses it, and the scattered inline normalization is removed.
- Normalize `sec_type` to a single vocabulary (`stock`, `etf`, `index`, `future`, `option`), case-insensitive. Legacy `STK` is accepted as `stock`. `sec_type` stays optional, and a prefix that contradicts it is rejected with 422.
- **Provider symbol mapping**:
  - Each price, options and volatility provider translates the canonical root and type into its native identifier, e.g. `I:SPX` becomes `.SPX` (LSEG), `$SPX` (Schwab), `I:SPX` (Polygon) or an IBKR `Index` contract. `F:ES` becomes `ESc1` (LSEG), `/ES` (Schwab) or the IBKR front-month/continuous future.
  - Canonical roots follow the primary listing symbols (e.g. CME Globex roots for futures). Provider deviations, such as `ZN` becoming `TYc1` on LSEG or `DJI` becoming `INDU` on IBKR, live in per-provider tables.
- **Implementation support declaration**: each provider declares which instrument types the hub has implemented for it (`price_sec_types`, `option_underlying_sec_types`, alongside the existing `volatility_sec_types`). A type without a hub implementation is rejected with 501 `CAPABILITY_NOT_SUPPORTED`. These sets describe code, never subscriptions, and are shown in the Admin UI.
- **Entitlement errors at runtime**: subscriptions are never hard-coded. The hub always forwards supported requests. When the provider denies access, it responds with the new uniform error `PROVIDER_NOT_ENTITLED` (HTTP 403), with provider details and the provider's message. Errors are not cached, so an upgraded subscription takes effect immediately. Configured graceful degradation, such as IBKR delayed data, stays in place.
- **Futures semantics**: `F:<ROOT>` means the front month. Last price returns the current front-month contract. History returns the provider's continuous front-month series, unadjusted. `PriceQuote` and `PriceBar` gain an optional `source_instrument`, such as `ESZ6` or `ESc1`, so the contract actually used is visible.
- **BREAKING**: Response `symbol` fields (and `underlying_symbol` for options) return the canonical notation, so index and future responses report `I:SPX` and `F:ES`. Stock and ETF responses are unchanged.
- **BREAKING**: A missing volatility entitlement changes from 503 `PROVIDER_NOT_AVAILABLE` with `reason=not_entitled` to 403 `PROVIDER_NOT_ENTITLED`.
- **BREAKING**: Price requests for index or future at providers without an implementation (e.g. Polygon futures) now return 501 instead of silently returning stock data.
- **BREAKING (cache only)**: Cache keys use the URL-encoded canonical symbol, and `sec_type` is folded into it. Existing entries expire through their TTL.
- Fix the IBKR last-price fallback so it keeps the instrument type. Fix IBKR futures prices so they resolve a concrete front month instead of an ambiguous `Future("ES", "CME")`.

## Capabilities

### New Capabilities
- `symbol-namespaces`: The symbol grammar, aliases, canonical form, `sec_type` vocabulary and conflict rules, the central parser and its use across REST, MCP and WebSocket, and per-endpoint type support.
- `provider-symbol-mapping`: Per-provider translation of canonical symbols into native identifiers, implementation support declarations with 501 handling, futures front-month semantics, `source_instrument` on prices, and Admin UI exposure.
- `provider-entitlement-errors`: The uniform `PROVIDER_NOT_ENTITLED` error and how each provider detects a missing entitlement at runtime.

### Modified Capabilities
- `response-caching`: The cache key `symbol` segment becomes the URL-encoded canonical symbol, and `sec_type` is folded into it.
- `underlying-implied-volatility`: Volatility accepts namespaced symbols and reports the canonical `symbol`. Missing entitlement maps to `PROVIDER_NOT_ENTITLED` (403) instead of `PROVIDER_NOT_AVAILABLE` (503).

## Impact

- **New**: `app/utils/symbols.py`, `ProviderNotEntitledError` in `app/utils/errors.py`, and tests.
- **Routes/MCP**: `routes_prices.py`, `routes_volatility.py`, `routes_options.py`, `routes_companies.py`, `routes_ws.py`, `routes_admin.py` (support sets) and `app/api/mcp.py`.
- **Services**: price, volatility, options, company and news services.
- **Cache**: `app/cache.py`.
- **Providers**: `base.py` (support sets), `ibkr.py`, `lseg.py`, `schwab.py`, `polygon.py`, `prixe.py` (native mapping, entitlement detection).
- **Models**: optional `source_instrument` on `PriceQuote` and `PriceBar`.
- **Admin UI**: `admin/src` shows the price and option support sets next to the volatility support.
- **Docs**: README, `doc/mcp-guide.md`, `.github/copilot-instructions.md`.
- **Clients**: must accept prefixed `symbol` values for index and future, handle 403 `PROVIDER_NOT_ENTITLED`, and handle 501 for unsupported provider/type combinations. No new dependencies.
