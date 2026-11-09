## ADDED Requirements

### Requirement: Implementation support declaration
Every price provider SHALL declare `price_sec_types` (last price) and `price_history_sec_types` (historical prices): the instrument types for which the hub implements a native symbol mapping for that operation. Every options provider SHALL declare `option_underlying_sec_types`. The defaults SHALL be `{stock, etf}`. These sets SHALL describe only what the hub's code implements, never what a user's subscription covers. `PriceService` and `OptionsService` SHALL check the set before calling the provider. An undeclared type SHALL be answered with HTTP 501 `CAPABILITY_NOT_SUPPORTED`, and the details SHALL include provider, operation, requested `sec_type` and the supported values. The existing `volatility_sec_types` and `volatility_history_sec_types` SHALL follow the same semantics.

#### Scenario: Future price at a provider without futures mapping
- **WHEN** a client calls `GET /prices/F:ES/last?provider=polygon`
- **THEN** the system responds with HTTP 501 `CAPABILITY_NOT_SUPPORTED` without calling Polygon, and `details.supported` lists Polygon's `price_sec_types`

#### Scenario: Type supported for quotes but not history
- **WHEN** `future` is in a provider's `price_sec_types` but not in its `price_history_sec_types`, and a client requests `GET /prices/F:ES/history` from that provider
- **THEN** the system responds with HTTP 501 `CAPABILITY_NOT_SUPPORTED` with operation `history`

#### Scenario: Supported type is always forwarded
- **WHEN** a client calls `GET /prices/I:SPX/last?provider=polygon` and `index` is in Polygon's `price_sec_types`
- **THEN** the request is sent to Polygon regardless of the user's subscription

### Requirement: Support sets in the admin API
`GET /api/admin/providers` SHALL expose `price_sec_types` and `price_history_sec_types` per price provider as `price_support` and `option_underlying_sec_types` per options provider as `options_support`, next to the existing `volatility_support`. The Admin UI SHALL display them in the provider details.

#### Scenario: Admin shows price support
- **WHEN** an admin opens the provider details for LSEG
- **THEN** the price support lists the types declared in LSEG's `price_sec_types`

### Requirement: Canonical roots and per-provider translation
Canonical roots SHALL be the primary listing symbols: index tickers as published by the index provider (`SPX`, `NDX`, `RUT`, `VIX`, `DJI`) and CME Globex roots for futures (`ES`, `NQ`, `RTY`, `YM`, `CL`, `NG`, `RB`, `HO`, `GC`, `SI`, `HG`, `ZC`, `ZW`, `ZS`, `ZN`, `ZB`). Each provider SHALL translate `(root, sec_type)` into its native identifier inside the provider. Provider deviations SHALL be kept in a per-provider root table. A root missing from a provider's table SHALL be passed through unchanged with the provider's type-specific decoration. The translation SHALL be:

| Type | IBKR | LSEG | Schwab | Polygon |
|---|---|---|---|---|
| stock/etf | `Stock(root, SMART, USD)` | equity RIC search (unchanged) | `root` | `root` |
| index | `Index(root', exchange)` | `.` + root' | `$` + root' | `I:` + root' |
| future | front-month `Future` / `ContFuture` | root' + `c1` | `/` + root' | — |

where root' is the root after the provider's deviation table (e.g. IBKR `DJI` becomes `INDU`, LSEG `ZN` becomes `TY`). Providers SHALL declare a type in their support set only after its translation has been verified against the provider's documentation or a live response.

#### Scenario: Index at LSEG
- **WHEN** `GET /prices/I:SPX/history?provider=lseg` is requested
- **THEN** LSEG is queried with `.SPX` and the response `symbol` is `I:SPX`

#### Scenario: Index at Schwab
- **WHEN** `GET /prices/I:SPX/last?provider=schwab` is requested
- **THEN** Schwab is queried with `$SPX`

#### Scenario: Future with deviating root at LSEG
- **WHEN** `GET /prices/F:ZN/history?provider=lseg` is requested
- **THEN** LSEG is queried with `TYc1`, the response `symbol` is `F:ZN` and `source_instrument` is `TYc1`

#### Scenario: Index with deviating root at IBKR
- **WHEN** `GET /prices/I:DJI/last?provider=ibkr` is requested
- **THEN** IBKR is queried with an `Index` contract for `INDU`

#### Scenario: Unknown root passes through
- **WHEN** `GET /prices/I:OEX/last?provider=lseg` is requested and `OEX` is not in LSEG's table
- **THEN** LSEG is queried with `.OEX`

#### Scenario: Option chain on an index at Schwab
- **WHEN** `GET /options/I:SPX/chain?provider=schwab` is requested and `index` is in Schwab's `option_underlying_sec_types`
- **THEN** Schwab is queried with underlying `$SPX` and the response `underlying_symbol` is `I:SPX`

### Requirement: Futures front-month semantics
`F:<ROOT>` SHALL denote the front-month future.
- Last price SHALL return a quote of the current front-month contract.
- Historical prices SHALL return the provider's continuous front-month series without back-adjustment, rolling per the provider's convention (IBKR `ContFuture`, LSEG `c1`, Schwab `/ROOT`).
- IBKR SHALL resolve the front month from contract details and SHALL NOT issue an ambiguous `Future(root, "CME")` request. It SHALL reuse the exchange table and front-month selection used for volatility.

#### Scenario: IBKR future last price
- **WHEN** `GET /prices/F:ES/last?provider=ibkr` is requested
- **THEN** IBKR qualifies the nearest non-expired `ES` contract on `CME` and the response `source_instrument` is its local symbol (e.g. `ESZ6`)

#### Scenario: IBKR future history
- **WHEN** `GET /prices/F:ES/history?provider=ibkr&interval=1d` is requested
- **THEN** IBKR historical data is requested for a `ContFuture` on `ES`

### Requirement: Source instrument on prices
`PriceQuote` and `PriceBar` SHALL have an optional field `source_instrument` holding the provider-native identifier actually queried when it differs from the root (e.g. `ESZ6`, `ESc1`, `.SPX`, `$SPX`). For stocks and ETFs it MAY be `null`. CSV exports SHALL include the column.

#### Scenario: Stock without source instrument
- **WHEN** `GET /prices/AAPL/last?provider=ibkr` is requested
- **THEN** `source_instrument` is `null` or `AAPL`

#### Scenario: LSEG future history
- **WHEN** `GET /prices/F:CL/history?provider=lseg` is requested
- **THEN** every bar has `source_instrument` `CLc1`

### Requirement: IBKR last-price fallback keeps the instrument type
When the IBKR last-price request falls back to historical bars, the fallback SHALL use the same resolved `sec_type` and contract as the original request.

#### Scenario: Index fallback
- **WHEN** `GET /prices/I:SPX/last?provider=ibkr` triggers the historical fallback
- **THEN** the fallback queries an IBKR `Index` contract for `SPX`, not a `Stock` contract
