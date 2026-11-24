## MODIFIED Requirements

### Requirement: Futures front-month semantics
`F:<ROOT>` SHALL denote the front-month future for prices and volatility.
- Last price SHALL return a quote of the current front-month contract.
- Historical prices SHALL return the provider's continuous front-month series without back-adjustment, rolling per the provider's convention (IBKR `ContFuture`, LSEG `c1`, Schwab `/ROOT`). The IBKR Web API has no continuous series and lists no expired contracts; `ibkrweb` SHALL return the history of the current front-month contract and SHALL document this deviation.
- IBKR SHALL resolve the front month from contract details and SHALL NOT issue an ambiguous `Future(root, "CME")` request. It SHALL reuse the exchange table and front-month selection used for volatility. `ibkrweb` SHALL apply the same seven-day buffer to contracts from `/trsrv/futures`, using `ltd` capped at `expirationDate` when both are present.
- Option chains SHALL NOT use the front month. For `GET /options/F:<ROOT>/chain`, the requested expiry and trading class determine the options, and the underlying is the futures contract those options are written on (capability `futures-option-chains`).

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

#### Scenario: Option chain beyond the front month
- **WHEN** the front-month `CL` contract is January 2027 and `GET /options/F:CL/chain?provider=ibkrweb&expiry=2027-01-14` is requested
- **THEN** the chain's `underlying_contract` is the February 2027 `CL` contract on which those options are written, not the front month
