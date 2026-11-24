## ADDED Requirements

### Requirement: Option chains on futures underlyings
`GET /options/{symbol}/chain` SHALL accept a futures root `F:<ROOT>` (e.g. `F:ES`, `F:CL`) as underlying together with a required `expiry`. The response SHALL contain the calls and puts of the futures options expiring on that date, filtered by `min_strike`, `max_strike` and `right` exactly as for equity chains. The response `underlying_symbol` SHALL be the canonical `F:<ROOT>`. A provider whose `option_underlying_sec_types` does not contain `future` SHALL be answered with HTTP 501 `CAPABILITY_NOT_SUPPORTED` without being called.

The initial verified roots for `ibkr` and `ibkrweb` SHALL be `ES` and `CL`. A request to either IBKR provider for another futures root SHALL return HTTP 501 `CAPABILITY_NOT_SUPPORTED` with `details.root` and `details.supported` listing verified roots, without an upstream request.

#### Scenario: ES chain via IBKR Web API
- **WHEN** a client calls `GET /options/F:ES/chain?provider=ibkrweb&expiry=2026-11-27&min_strike=7200&max_strike=7300`
- **THEN** the response contains calls and puts for the listed strikes between 7200 and 7300 expiring on 2026-11-27, and `underlying_symbol` is `F:ES`

#### Scenario: Provider without futures options
- **WHEN** a client calls `GET /options/F:ES/chain?provider=schwab&expiry=2026-11-27`
- **THEN** the system responds with HTTP 501 `CAPABILITY_NOT_SUPPORTED`, operation `option_chain`, and `details.supported` lists Schwab's `option_underlying_sec_types`

#### Scenario: Expiry without futures options
- **WHEN** no futures option on the root expires on the requested date
- **THEN** the response is an empty chain with the provider name, like an unlisted equity expiry

### Requirement: Underlying contract selected by expiry
For a futures chain, the underlying SHALL be the futures contract on which the selected options are written, as reported by the provider. It SHALL NOT be the front month of `F:<ROOT>`. The chain SHALL report this contract in `underlying_contract` (provider-native local symbol, e.g. `ESZ6`, `CLF7`) and its current price in `underlying_price`. The price SHALL be the last price, else the close, else `null`, in the same market data type as the option snapshots.

#### Scenario: Crude oil options on the following month's future
- **WHEN** `GET /options/F:CL/chain?provider=ibkrweb&expiry=2026-12-16` is requested
- **THEN** `underlying_contract` names the January 2027 `CL` contract and `underlying_price` is that contract's price

#### Scenario: ES weekly options on the quarterly future
- **WHEN** `GET /options/F:ES/chain?provider=ibkrweb&expiry=2026-11-27` is requested
- **THEN** `underlying_contract` names the December 2026 `ES` contract

### Requirement: Trading class selection
The chain endpoint SHALL accept an optional query parameter `trading_class` (case-insensitive). When several option trading classes of the root expire on the requested date, the provider SHALL select:
1. the class given in `trading_class`;
2. otherwise the verified exchange standard class (`ES` for `ES`, `LO` for `CL`) if listed for that date;
3. otherwise the only class listed for that date.

If no class can be selected, the request SHALL fail with HTTP 422 `DATA_VALIDATION_ERROR`, and `details.trading_classes` SHALL list the available classes. A `trading_class` that is not listed for the date SHALL produce an empty chain. The response SHALL report the selected class in `trading_class`. A chain SHALL never mix contracts of different classes. For stock, ETF and index underlyings the parameter SHALL be ignored.

#### Scenario: Quarterly and weekly class on the same date
- **WHEN** `GET /options/F:ES/chain?provider=ibkrweb&expiry=2026-12-18` is requested without `trading_class`, and `ES` (regular) and `EW3` both expire on that date
- **THEN** the chain contains only `ES` class contracts and `trading_class` is `ES`

#### Scenario: Explicit weekly class
- **WHEN** the same request carries `trading_class=EW3`
- **THEN** the chain contains only `EW3` contracts and `trading_class` is `EW3`

#### Scenario: Standard and weekly CL contracts use different futures
- **WHEN** a client requests `F:CL` for 2026-12-16 and `LO` and `WL3` are both listed
- **THEN** the default chain uses `LO` and `CLF7`; an explicit `trading_class=WL3` uses `CLG7`

#### Scenario: Ambiguous date
- **WHEN** two non-regular classes expire on the requested date and no `trading_class` is given
- **THEN** the system responds with HTTP 422 `DATA_VALIDATION_ERROR` and `details.trading_classes` lists both classes

### Requirement: Chain contract metadata
`OptionChain` SHALL have the optional fields `underlying_contract` (string), `underlying_price` (decimal), `multiplier` (decimal), `trading_class` (string) and `exchange` (string). For futures chains, `multiplier` SHALL be the contract multiplier reported by the provider (e.g. `50` for ES, `1000` for CL), and `exchange` the listing exchange (e.g. `CME`, `NYMEX`). Providers that do not supply a value SHALL return `null`, and existing equity and index chains SHALL remain valid without them. CSV output SHALL repeat these chain-level values as columns on every option row.

#### Scenario: Multiplier for crude oil
- **WHEN** a `F:CL` chain is returned by `ibkrweb`
- **THEN** `multiplier` is `1000` and `exchange` is `NYMEX`

#### Scenario: Equity chain unchanged
- **WHEN** `GET /options/AAPL/chain?provider=schwab&expiry=2026-12-18` is requested
- **THEN** the response validates against the previous schema, and the new fields are absent or `null`

### Requirement: Futures option chains over TWS
The TWS provider `ibkr` SHALL declare `future` in `option_underlying_sec_types`. For a futures root, `get_option_chain` SHALL request `reqContractDetails` for a `FuturesOption` with the root, `lastTradeDateOrContractMonth` = expiry (`YYYYMMDD`) and the exchange from the shared futures exchange table (adding `right` when only one is requested). It SHALL then:
1. apply the trading-class selection of this capability to the returned contracts, using each contract's `tradingClass`;
2. filter by `min_strike`/`max_strike`;
3. take `multiplier`, exchange and the underlying futures conid (`underConId`) from the contract details;
4. request snapshots for the options and the underlying future through the existing ticker snapshot path, mapped as for equity chains, with `symbol` = the contract's `localSymbol`.

It SHALL NOT construct `Option(symbol, …, "SMART")` contracts for futures roots. The response SHALL fill the same chain metadata fields as `ibkrweb`. The behaviour SHALL be identical between `ibkr` and `ibkrweb` for the same account, apart from the provider name.

#### Scenario: ES chain via TWS
- **WHEN** `GET /options/F:ES/chain?provider=ibkr&expiry=2026-11-27&min_strike=7200&max_strike=7300` is requested
- **THEN** the TWS provider requests contract details for `FuturesOption` `ES` on `CME` expiring 2026-11-27 and returns the selected class's calls and puts with `multiplier` `50`, `exchange` `CME` and the December 2026 ES future as `underlying_contract`

#### Scenario: Same result as the Web API
- **WHEN** the same `F:CL` chain is requested from `ibkr` and from `ibkrweb` for one account
- **THEN** both responses have the same strikes, `trading_class`, `multiplier`, `exchange` and `underlying_contract`

#### Scenario: TWS not connected
- **WHEN** a futures chain is requested from `ibkr` while TWS/IB Gateway is unreachable
- **THEN** the request fails with the provider's existing connection error mapping, exactly as for equity chains

### Requirement: Futures option identifiers
Each `OptionQuote` in a futures chain SHALL carry `symbol` = the provider-native local symbol of the futures option (no OCC format exists for futures options). The option quote endpoint `GET /options/{symbol}/quote/{option_id}` SHALL continue to reject `future` underlyings with HTTP 422 until a separate change defines futures-option quotes.

#### Scenario: Native option symbol
- **WHEN** a `F:ES` chain is returned by `ibkrweb`
- **THEN** each option `symbol` is the IBKR local symbol of that contract and `underlying_symbol` is `F:ES`

#### Scenario: Futures option quote still rejected
- **WHEN** a client calls `GET /options/F:ES/quote/<any id>`
- **THEN** the system responds with HTTP 422 `DATA_VALIDATION_ERROR` without calling a provider
