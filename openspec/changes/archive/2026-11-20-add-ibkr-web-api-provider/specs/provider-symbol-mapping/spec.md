## MODIFIED Requirements

### Requirement: Canonical roots and per-provider translation
Canonical roots SHALL be the primary listing symbols: index tickers as published by the index provider (`SPX`, `NDX`, `RUT`, `VIX`, `DJI`) and CME Globex roots for futures (`ES`, `NQ`, `RTY`, `YM`, `CL`, `NG`, `RB`, `HO`, `GC`, `SI`, `HG`, `ZC`, `ZW`, `ZS`, `ZN`, `ZB`). Each provider SHALL translate `(root, sec_type)` into its native identifier inside the provider. Provider deviations SHALL be kept in a per-provider root table. A root missing from a provider's table SHALL be passed through unchanged with the provider's type-specific decoration. The translation SHALL be:

| Type | IBKR | IBKR Web API | LSEG | Schwab | Polygon |
|---|---|---|---|---|---|
| stock/etf | `Stock(root, SMART, USD)` | US `STK` conid from `/trsrv/stocks` | equity RIC search (unchanged) | `root` | `root` |
| index | `Index(root', exchange)` | `IND` conid from `/iserver/secdef/search` for root' | `.` + root' | `$` + root' | `I:` + root' |
| future | front-month `Future` / `ContFuture` | front-month conid from `/trsrv/futures` | root' + `c1` | `/` + root' | — |

where root' is the root after the provider's deviation table (e.g. IBKR `DJI` becomes `INDU`, LSEG `ZN` becomes `TY`). `ibkr` and `ibkrweb` SHALL share one IBKR root table, index exchange table and futures exchange table. `ibkrweb` SHALL override the exchange for `INDU` to `CME` as returned by CPGW; the TWS mapping remains `NYSE`. Providers SHALL declare a type in their support set only after its translation has been verified against the provider's documentation or a live response.

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

#### Scenario: Index with deviating root at the IBKR Web API
- **WHEN** `GET /prices/I:DJI/last?provider=ibkrweb` is requested
- **THEN** the Web API is searched for the index `INDU` and the response `symbol` is `I:DJI`

#### Scenario: Unknown root passes through
- **WHEN** `GET /prices/I:OEX/last?provider=lseg` is requested and `OEX` is not in LSEG's table
- **THEN** LSEG is queried with `.OEX`

#### Scenario: Option chain on an index at Schwab
- **WHEN** `GET /options/I:SPX/chain?provider=schwab` is requested and `index` is in Schwab's `option_underlying_sec_types`
- **THEN** Schwab is queried with underlying `$SPX` and the response `underlying_symbol` is `I:SPX`

### Requirement: Futures front-month semantics
`F:<ROOT>` SHALL denote the front-month future.
- Last price SHALL return a quote of the current front-month contract.
- Historical prices SHALL return the provider's continuous front-month series without back-adjustment, rolling per the provider's convention (IBKR `ContFuture`, LSEG `c1`, Schwab `/ROOT`). The IBKR Web API has no continuous series and lists no expired contracts; `ibkrweb` SHALL return the history of the current front-month contract and SHALL document this deviation.
- IBKR SHALL resolve the front month from contract details and SHALL NOT issue an ambiguous `Future(root, "CME")` request. It SHALL reuse the exchange table and front-month selection used for volatility. `ibkrweb` SHALL apply the same seven-day buffer to contracts from `/trsrv/futures`, using `ltd` capped at `expirationDate` when both are present.

#### Scenario: IBKR future last price
- **WHEN** `GET /prices/F:ES/last?provider=ibkr` is requested
- **THEN** IBKR qualifies the nearest non-expired `ES` contract on `CME` and the response `source_instrument` is its local symbol (e.g. `ESZ6`)

#### Scenario: IBKR future history
- **WHEN** `GET /prices/F:ES/history?provider=ibkr&interval=1d` is requested
- **THEN** IBKR historical data is requested for a `ContFuture` on `ES`

#### Scenario: IBKR Web API future last price
- **WHEN** `GET /prices/F:ES/last?provider=ibkrweb` is requested
- **THEN** the same front-month contract as with `ibkr` is used and `source_instrument` is its local symbol

#### Scenario: IBKR Web API future history
- **WHEN** `GET /prices/F:ES/history?provider=ibkrweb&interval=1d` is requested
- **THEN** the history of the front-month contract is returned with `source_instrument` set to its local symbol
