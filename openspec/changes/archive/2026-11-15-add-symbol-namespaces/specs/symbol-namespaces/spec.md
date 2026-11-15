## ADDED Requirements

### Requirement: Namespaced symbol grammar
The system SHALL accept instrument symbols in the form `[<NS>:]<ROOT>`, case-insensitively. The namespace prefixes SHALL be:
- `F:` for a future, which maps to `sec_type` `future`
- `I:` for an index, which maps to `sec_type` `index`
- `O:` for an option contract identified by its OCC symbol, which maps to `sec_type` `option`
- no prefix for a stock or ETF, which maps to `sec_type` `stock` unless an explicit `sec_type` of `etf` is given

The system SHALL also accept these aliases:
- a leading `^` (e.g. `^SPX`), equivalent to `I:`
- a leading `/` (e.g. `/ES`), equivalent to `F:`

Surrounding whitespace SHALL be ignored. The root SHALL be upper-cased. An unknown prefix, an empty root, or a root containing `:` SHALL be rejected with HTTP 422 and error code `DATA_VALIDATION_ERROR`.

Provider-native notations SHALL NOT be accepted as input: a leading `.` (LSEG RIC style) or `$` (Schwab style). Such symbols SHALL be rejected with HTTP 422 and error code `DATA_VALIDATION_ERROR`, and the details SHALL suggest the canonical form (e.g. `I:SPX`). Provider-native identifiers remain reachable only through explicit override parameters such as `ric`.

#### Scenario: Future prefix
- **WHEN** the symbol `f:es` is parsed
- **THEN** the result is root `ES`, sec_type `future` and canonical symbol `F:ES`

#### Scenario: Index prefix
- **WHEN** the symbol `I:SPX` is parsed
- **THEN** the result is root `SPX`, sec_type `index` and canonical symbol `I:SPX`

#### Scenario: Index alias
- **WHEN** the symbol `^spx` is parsed
- **THEN** the result is root `SPX`, sec_type `index` and canonical symbol `I:SPX`

#### Scenario: Future alias
- **WHEN** the symbol `/ES` is parsed
- **THEN** the result is root `ES`, sec_type `future` and canonical symbol `F:ES`

#### Scenario: Bare symbol
- **WHEN** the symbol ` aapl ` is parsed
- **THEN** the result is root `AAPL`, sec_type `stock` and canonical symbol `AAPL`

#### Scenario: Option prefix
- **WHEN** the symbol `O:AAPL250117C00150000` is parsed
- **THEN** the result is root `AAPL250117C00150000`, sec_type `option` and canonical symbol `O:AAPL250117C00150000`

#### Scenario: Unknown prefix
- **WHEN** the symbol `X:BTCUSD` is parsed
- **THEN** the system responds with HTTP 422 and error code `DATA_VALIDATION_ERROR`, and the error details list the supported prefixes

#### Scenario: Empty root
- **WHEN** the symbol `F:` is parsed
- **THEN** the system responds with HTTP 422 and error code `DATA_VALIDATION_ERROR`

#### Scenario: Provider-native notation rejected
- **WHEN** the symbol `.SPX` or `$SPX` is parsed
- **THEN** the system responds with HTTP 422, error code `DATA_VALIDATION_ERROR` and a suggestion of `I:SPX`

### Requirement: Unified sec_type vocabulary
The optional `sec_type` parameter SHALL accept the values `stock`, `etf`, `index`, `future` and `option`, case-insensitively, on every REST route and MCP tool that accepts it. The legacy value `STK` SHALL be accepted as `stock`. Any other value SHALL be rejected with HTTP 422 and error code `DATA_VALIDATION_ERROR`.

#### Scenario: Upper-case sec_type
- **WHEN** a client calls `GET /volatility/SPX?sec_type=INDEX`
- **THEN** the request is treated as the index `I:SPX`

#### Scenario: Legacy STK
- **WHEN** an internal caller passes `sec_type="STK"` with symbol `AAPL`
- **THEN** the request is treated as the stock `AAPL`

#### Scenario: Invalid sec_type
- **WHEN** a client calls `GET /prices/AAPL/last?sec_type=bond`
- **THEN** the system responds with HTTP 422 and error code `DATA_VALIDATION_ERROR`

### Requirement: Prefix and sec_type resolution
When a symbol carries a namespace prefix or alias and `sec_type` is also given, both SHALL denote the same type. Otherwise the request SHALL be rejected with HTTP 422 and error code `DATA_VALIDATION_ERROR`, with the details naming both values. When the symbol has no prefix, an explicit `sec_type` SHALL determine the type. `etf` SHALL only be combined with a bare symbol.

#### Scenario: Matching prefix and sec_type
- **WHEN** a client calls `GET /volatility/F:ES?sec_type=future`
- **THEN** the request is treated as the future `F:ES`

#### Scenario: Contradicting prefix and sec_type
- **WHEN** a client calls `GET /volatility/F:ES?sec_type=stock`
- **THEN** the system responds with HTTP 422 and error code `DATA_VALIDATION_ERROR`

#### Scenario: Legacy sec_type with bare symbol
- **WHEN** a client calls `GET /volatility/ES?sec_type=future`
- **THEN** the request is treated exactly like `GET /volatility/F:ES`

#### Scenario: ETF on bare symbol
- **WHEN** a client calls `GET /volatility/SPY?sec_type=etf`
- **THEN** the request is treated as the ETF `SPY` and the response `sec_type` is `etf`

### Requirement: Central symbol parser
The system SHALL provide one parser that turns a raw symbol and an optional `sec_type` into a `ParsedSymbol` with `root`, `sec_type` and `canonical`. Every REST route, MCP tool handler, WebSocket subscription and cache key builder that receives a symbol SHALL use this parser. Providers SHALL continue to receive the bare `root` together with the resolved `sec_type`, never a prefixed symbol.

#### Scenario: Provider receives bare root
- **WHEN** a client calls `GET /prices/F:ES/history?provider=ibkr`
- **THEN** the IBKR provider is called with symbol `ES` and sec_type `future`

#### Scenario: Same result on REST and MCP
- **WHEN** a client calls `GET /volatility/I:SPX/stats` and an MCP client calls `get_implied_volatility_stats` with `{"symbol": "I:SPX"}`
- **THEN** both calls resolve to the same root, sec_type, provider request and cache entry, apart from the MCP channel marker

### Requirement: Canonical symbol in responses
Response fields that identify the requested instrument SHALL contain the canonical symbol: `symbol` in `PriceQuote`, `PriceBar`, `VolatilitySnapshot`, `VolatilityHistory` and `VolatilityStats`, and `underlying_symbol` in `OptionChain` and `OptionQuote`. Stock and ETF symbols SHALL appear without a prefix. Fields that describe provider-specific instruments, such as `source_instrument`, `underlying` and `option_id`, SHALL keep their provider value. CSV export filenames SHALL contain the canonical symbol URL-encoded.

#### Scenario: Index price
- **WHEN** a client calls `GET /prices/^SPX/last?provider=ibkr`
- **THEN** the response `symbol` is `I:SPX`

#### Scenario: Future volatility via legacy parameter
- **WHEN** a client calls `GET /volatility/ES?sec_type=future&provider=lseg`
- **THEN** the response `symbol` is `F:ES`, `sec_type` is `future` and `source_instrument` is `ESATMIV`

#### Scenario: Stock unchanged
- **WHEN** a client calls `GET /prices/aapl/last`
- **THEN** the response `symbol` is `AAPL`

### Requirement: Per-endpoint namespace support
Each symbol-accepting endpoint SHALL declare the instrument types it serves. A request for any other type SHALL be rejected with HTTP 422 and error code `DATA_VALIDATION_ERROR` before any provider is called. The error details SHALL include the parsed `sec_type` and the supported types. The supported types SHALL be:
- prices (last, history): `stock`, `etf`, `index`, `future`
- volatility (snapshot, history, stats): `stock`, `etf`, `index`, `future`
- option chain: `stock`, `etf`, `index` (the underlying)
- option quote: the `option_id` path parameter MAY carry the `O:` prefix, which SHALL be stripped; the `{symbol}` underlying accepts `stock`, `etf`, `index`
- company profile, company news: `stock`, `etf`
- WebSocket price subscription: `stock`, `etf`, `index`, `future`

Provider-level implementation support checks (capability `provider-symbol-mapping`) SHALL apply after this check.

#### Scenario: Company profile for a future
- **WHEN** a client calls `GET /companies/F:ES`
- **THEN** the system responds with HTTP 422 and error code `DATA_VALIDATION_ERROR` without calling a provider

#### Scenario: Option chain on an index
- **WHEN** a client calls `GET /options/I:SPX/chain?provider=schwab`
- **THEN** the Schwab provider is called with underlying `SPX`

#### Scenario: Option quote with prefixed option id
- **WHEN** a client calls `GET /options/AAPL/quote/O:AAPL250117C00150000`
- **THEN** the provider is called with option id `AAPL250117C00150000`

### Requirement: Alias availability per transport
The `/` alias SHALL be accepted wherever the symbol is not a URL path segment: MCP arguments, WebSocket messages and query parameters. REST path segments SHALL use the `F:` prefix for futures. The `^` alias and all `F:`, `I:` and `O:` prefixes SHALL be accepted in REST path segments.

#### Scenario: Future alias over MCP
- **WHEN** an MCP client calls `get_last_price` with `{"symbol": "/ES"}`
- **THEN** the request is treated as the future `F:ES`

#### Scenario: Colon in REST path
- **WHEN** a client calls `GET /volatility/F:ES/stats`
- **THEN** the route matches and the request is treated as the future `F:ES`
