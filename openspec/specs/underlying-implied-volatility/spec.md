# underlying-implied-volatility Specification

## Purpose
Provide provider-agnostic underlying implied-volatility snapshots, daily history and IV Rank/IV Percentile for stocks, ETFs, indices and futures through REST and MCP, with normalized units, explicit provider support, validated instrument identity and consistent error handling. Ensure option-contract implied volatility also uses decimal fractions across providers.

## Requirements

### Requirement: Volatility provider capability
The system SHALL define a provider capability `BaseVolatilityProvider` with the operations `get_implied_volatility` (snapshot) and `get_implied_volatility_history` (daily history) for an underlying instrument. The instrument SHALL be identified by `symbol`, `sec_type` (`stock`, `etf`, `index`, `future`) and an optional explicit `ric`. Providers implementing this base SHALL be reported with the capability name `volatility`.

#### Scenario: Provider implements the capability
- **WHEN** a provider class inherits from `BaseVolatilityProvider`
- **THEN** the registry SHALL accept it as a volatility provider and the admin provider listing SHALL include `volatility` in its `capabilities`

#### Scenario: Provider without the capability is requested
- **WHEN** a client requests volatility data with `provider=<name>` for a provider that does not implement `BaseVolatilityProvider`
- **THEN** the system SHALL respond with HTTP 400 and error code `INVALID_PROVIDER`

### Requirement: Provider support declaration
Each `BaseVolatilityProvider` SHALL declare three sets:
- `volatility_sec_types`: sec_types supported for snapshots
- `volatility_history_sec_types`: sec_types supported for history and stats
- `volatility_tenors`: tenors with real values

The `VolatilityService` SHALL check these sets before calling the provider. An unsupported sec_type, operation or history tenor SHALL be answered with HTTP 501 and error code `CAPABILITY_NOT_SUPPORTED`. The error details SHALL include the provider, the operation and the supported values. `GET /api/admin/providers` SHALL expose the sets per volatility provider as `volatility_support`.

#### Scenario: Unsupported history sec_type
- **WHEN** a client calls `GET /volatility/ES/history?sec_type=future&provider=ibkr`
- **THEN** the system SHALL respond with HTTP 501, code `CAPABILITY_NOT_SUPPORTED`, with `details.supported` listing `stock`, `etf` and `index`, without calling IBKR

#### Scenario: Unsupported history tenor
- **WHEN** a client calls `GET /volatility/AAPL/history?provider=ibkr&tenor_days=60`
- **THEN** the system SHALL respond with HTTP 501 and code `CAPABILITY_NOT_SUPPORTED`

### Requirement: Normalized volatility units
All implied volatility values SHALL be annualized decimal fractions, represented as `Decimal` and quantized to 4 decimal places with `ROUND_HALF_UP` (e.g. `0.2676` for 26.76 %). This SHALL hold for every provider, independent of the unit used upstream. It covers:
- `iv_call`, `iv_put` and `iv` in snapshots and history points
- `current`, `min` and `max` in stats

`iv_rank` and `iv_percentile` SHALL be expressed on a 0–100 scale with 2 decimal places.

#### Scenario: LSEG returns percent values
- **WHEN** LSEG returns `26.76` for `30D_A_IM_C`
- **THEN** the response SHALL contain `iv_call` equal to `0.2676` for tenor 30

#### Scenario: IBKR returns long fractions
- **WHEN** IBKR returns `0.2519055923990361` as implied volatility
- **THEN** the response SHALL contain `iv` equal to `0.2519`

#### Scenario: Same format across providers
- **WHEN** the same symbol is requested from `lseg` and `ibkr`
- **THEN** both responses SHALL use the same model, fraction scale and precision, differing only in values, `method`, `source_instrument`, `market` and `provider`

#### Scenario: Combined IV value
- **WHEN** both `iv_call` and `iv_put` are present for a tenor
- **THEN** `iv` SHALL equal their arithmetic mean
- **WHEN** only one of `iv_call` or `iv_put` is present
- **THEN** `iv` SHALL equal that value
- **WHEN** the provider delivers a single combined value (IBKR)
- **THEN** `iv` SHALL equal that value and `iv_call` and `iv_put` SHALL be `null`
- **WHEN** no value is available
- **THEN** `iv` SHALL be `null`

### Requirement: Uniform tenor list
`implied` in every snapshot SHALL always contain exactly three entries, for `tenor_days` 30, 60 and 90 in this order. For a tenor that the provider cannot deliver, `iv_call`, `iv_put` and `iv` SHALL all be `null`.

#### Scenario: IBKR delivers only 30 days
- **WHEN** `GET /volatility/AAPL?provider=ibkr` succeeds
- **THEN** `implied` SHALL contain three entries; tenors 60 and 90 SHALL have all values `null`

### Requirement: Option contract IV units (Schwab normalization)
`OptionQuote.implied_volatility` SHALL be a decimal fraction for every options provider. The Schwab provider SHALL divide its upstream `volatility` by 100. It SHALL map missing values (`null`, NaN, or negative sentinels such as `-999`) to `null`. This is a **breaking change** for consumers of Schwab option chains and quotes.

#### Scenario: Schwab option chain
- **WHEN** Schwab returns `"volatility": 22.345` for a contract
- **THEN** `GET /options/{symbol}/chain?provider=schwab` SHALL return `implied_volatility` `0.22345`

#### Scenario: Schwab sentinel
- **WHEN** Schwab returns `"volatility": -999.0`
- **THEN** `implied_volatility` SHALL be `null`

### Requirement: Implied volatility snapshot endpoint
The system SHALL expose `GET /volatility/{symbol}` returning a `VolatilitySnapshot` with these fields:
- `symbol`, `sec_type`, `source_instrument`
- `method`: `provider_atm_index` (LSEG) or `provider_model_30d` (IBKR)
- `underlying`, `underlying_name`, `market`
- `as_of`
- `implied`: one entry per tenor of 30, 60 and 90 days, each with `iv_call`, `iv_put` and `iv`
- `provider`

The endpoint SHALL accept the query parameters `sec_type` (default `stock`), `ric`, `provider` and `format` (`json` default, `csv`).

#### Scenario: Stock snapshot via default provider
- **WHEN** `default_volatility_provider` is `lseg` and a client calls `GET /volatility/AAPL`
- **THEN** the system SHALL return HTTP 200 with `source_instrument` `AAPLATMIV.U`, `market` `OPRA`, `provider` `lseg` and `implied` entries for tenors 30, 60 and 90

#### Scenario: Index snapshot
- **WHEN** a client calls `GET /volatility/SPX?sec_type=index&provider=lseg`
- **THEN** the system SHALL query `SPXATMIV.U` and return `underlying` `.SPX`

#### Scenario: Future snapshot
- **WHEN** a client calls `GET /volatility/ES?sec_type=future&provider=lseg`
- **THEN** the system SHALL query `ESATMIV` (not `ESATMIV.U`) and return a `market` of `COMFUT` or `CMEG`

#### Scenario: Explicit instrument override
- **WHEN** a client calls `GET /volatility/DAX?ric=GDAXATMIV.EX&provider=lseg`
- **THEN** the system SHALL query `GDAXATMIV.EX` verbatim, report it as `source_instrument` and return its `market` without validating it against `sec_type`

#### Scenario: CSV export
- **WHEN** a client calls `GET /volatility/AAPL?format=csv`
- **THEN** the system SHALL return a CSV attachment containing the snapshot data

#### Scenario: No default and no provider
- **WHEN** no `default_volatility_provider` is configured and no `provider` query parameter is given
- **THEN** the system SHALL respond with the same error behavior as other capabilities without a configured default

### Requirement: Underlying market validation
For LSEG requests without an explicit `ric`, the provider SHALL validate that the market of the resolved instrument matches the requested `sec_type`. IBKR resolves instruments by explicit security type and are not subject to this check. The rules:
- `stock`, `etf` and `index` SHALL require market `OPRA`.
- `future` SHALL require market `COMFUT` or `CMEG`.

On mismatch, the system SHALL respond with HTTP 422 and error code `DATA_VALIDATION_ERROR`. The error details SHALL include the expected markets, the actual `market` and the `underlying_name`.

#### Scenario: Ticker collision is rejected
- **WHEN** the provider resolves an instrument whose market does not match the requested `sec_type`
- **THEN** the system SHALL respond with HTTP 422 instead of returning data for a different underlying

#### Scenario: Equity ticker that equals a futures root
- **WHEN** a client calls `GET /volatility/CL` (default `sec_type=stock`)
- **THEN** the response SHALL succeed with `underlying_name` identifying Colgate-Palmolive and `market` `OPRA`, making the identity of the underlying explicit

### Requirement: Implied volatility history endpoint
The system SHALL expose `GET /volatility/{symbol}/history` returning a `VolatilityHistory` with `symbol`, `sec_type`, `source_instrument`, `tenor_days`, `provider` and `points`. Each point SHALL contain `date`, `iv_call`, `iv_put` and `iv`, and `points` SHALL be sorted ascending by date. The endpoint SHALL accept these parameters:
- `start` (default: `end` minus 365 days)
- `end` (default: today)
- `tenor_days` (`30`, `60` or `90`, default `30`)
- `sec_type`, `ric`, `provider` and `format`

#### Scenario: Default window supports IV Rank and IV Percentile
- **WHEN** a client calls `GET /volatility/AAPL/history` without `start`/`end`
- **THEN** the system SHALL return daily points covering the last 365 calendar days (≥ 252 trading days when available)

#### Scenario: Daily history for a stock
- **WHEN** a client calls `GET /volatility/AAPL/history?start=2026-10-01&end=2026-10-31&provider=lseg`
- **THEN** the system SHALL return daily 30-day-tenor points between those dates in ascending order

#### Scenario: Points without data are omitted
- **WHEN** the upstream returns a date where both call and put IV are missing
- **THEN** that date SHALL NOT appear in `points`

#### Scenario: Invalid tenor
- **WHEN** a client calls the history endpoint with `tenor_days=45`
- **THEN** the system SHALL respond with HTTP 422

#### Scenario: Invalid date range
- **WHEN** `start` is after `end`
- **THEN** the system SHALL respond with HTTP 422

### Requirement: IV Rank and IV Percentile endpoint
The system SHALL expose `GET /volatility/{symbol}/stats` returning a `VolatilityStats` with the fields `symbol`, `sec_type`, `source_instrument`, `tenor_days`, `provider`, `window`, `window_points`, `window_start`, `window_end`, `current`, `min`, `max`, `iv_rank` and `iv_percentile`.

The service layer SHALL compute the values from the provider's IV history over the last `window` daily points, independent of the provider:
- `current` is the `iv` of the most recent point.
- `iv_rank` = (current − min) / (max − min) × 100.
- `iv_percentile` = the share of window points, excluding the current one, that are strictly below `current`, × 100.
- `iv_rank` and `iv_percentile` SHALL be rounded to 2 decimals.

The endpoint SHALL accept `window` (integer 20–756, default 252), `tenor_days` (30, 60 or 90, default 30), `sec_type`, `ric`, `provider` and `format`.

#### Scenario: Default 52-week stats
- **WHEN** a client calls `GET /volatility/AAPL/stats`
- **THEN** the system SHALL fetch enough 30-day-tenor history to cover 252 trading days and return `window` 252, `window_points` ≤ 252, and `iv_rank` and `iv_percentile` between 0 and 100

#### Scenario: Correct computation
- **WHEN** the window contains the values 0.20, 0.10, 0.30, 0.25 (oldest to newest)
- **THEN** `current` SHALL be 0.25, `min` 0.10, `max` 0.30, `iv_rank` 75.00 and `iv_percentile` 66.67

#### Scenario: Flat window
- **WHEN** all points in the window have the same value
- **THEN** `iv_rank` SHALL be `null` and `iv_percentile` SHALL be 0

#### Scenario: Insufficient history
- **WHEN** fewer than 20 usable points are available
- **THEN** the system SHALL respond with HTTP 404, code `DATA_NOT_FOUND` and `details.reason` `insufficient_history`

#### Scenario: Window out of range
- **WHEN** a client calls the stats endpoint with `window=5`
- **THEN** the system SHALL respond with HTTP 422

### Requirement: LSEG volatility implementation
`LSEGProvider` SHALL implement `BaseVolatilityProvider` with the following behavior:
- **Snapshot**: reads the FIDs `30D_A_IM_C`, `30D_A_IM_P`, `60D_A_IM_C`, `60D_A_IM_P`, `90D_A_IM_C`, `90D_A_IM_P`, `TRADE_DATE`, `UNDERLYING`, `INST_DESC` and `GN_TXT16_5` via the streaming snapshot path (`rd.get_data`). It SHALL NOT use `TR.*` datagrid fields or REST pricing snapshots.
- **History**: uses `historical_pricing.summaries` at daily interval, with explicit fields for the requested tenor.
- **Instrument resolution**, unless `ric` is given (symbol upper-cased, leading `^` and `.` removed):
  - `{SYMBOL}ATMIV.U` for `stock`, `etf` and `index`
  - `{SYMBOL}ATMIV` for `future`
- **Operational behavior**: calls SHALL use the existing session handling, throttling and retry. The provider SHALL NOT keep its own snapshot cache. Caching is provided by the shared response cache (see `response-caching`).

#### Scenario: Instrument resolution for ETF
- **WHEN** `get_implied_volatility("spy", sec_type="etf")` is called
- **THEN** the provider SHALL request `SPYATMIV.U`

#### Scenario: Instrument resolution for index with prefix
- **WHEN** `get_implied_volatility("^SPX", sec_type="index")` is called
- **THEN** the provider SHALL request `SPXATMIV.U`

#### Scenario: No provider-level cache
- **WHEN** `get_implied_volatility` is called twice on the provider directly
- **THEN** the provider SHALL issue two upstream requests

### Requirement: IBKR volatility implementation
`IBKRProvider` SHALL implement `BaseVolatilityProvider` with the declared support:
- snapshot: `stock`, `etf`, `index`, `future`
- history: `stock`, `etf`, `index`
- tenors: 30

**Instrument resolution:**
- `stock`/`etf` → `Stock(SYM, "SMART", "USD")`.
- `index` → `Index(SYM, exchange)`, with `RUT` → `RUSSELL`, `NDX` → `NASDAQ`, `SPX`/`VIX` → `CBOE`.
- `future` → the nearest contract whose last trade date is at least 7 days ahead. The exchange comes from a built-in root map (ES/NQ/RTY → CME, YM/ZC/ZW/ZS/ZN/ZB → CBOT, CL/NG/RB/HO → NYMEX, GC/SI/HG → COMEX). An unknown root SHALL resolve only if exactly one exchange matches.

**Snapshot:**
- SHALL use a streaming market-data request with generic tick `106`, never snapshot mode.
- SHALL wait at most `IBKR_IV_TIMEOUT_SECONDS` (default 10) for a finite value > 0 and SHALL always cancel the subscription.
- SHALL use the configured market data type (default delayed). If live data is refused as not subscribed, it SHALL retry once with delayed data.
- `method` SHALL be `provider_model_30d`. `source_instrument` SHALL be the contract `localSymbol`, `underlying_name` the contract `longName`, and `market` the primary exchange or exchange.

**History:**
- SHALL use `reqHistoricalData` with `whatToShow=OPTION_IMPLIED_VOLATILITY`, daily bars and RTH only.
- Each point's `iv` SHALL be the bar close, with `iv_call`/`iv_put` `null`. Bars with close ≤ 0 SHALL be dropped.

The `ric` parameter SHALL be rejected with HTTP 422 for this provider.

#### Scenario: Stock snapshot with delayed data
- **WHEN** `GET /volatility/AAPL?provider=ibkr` is requested and IBKR runs with delayed data
- **THEN** the response SHALL contain tenor 30 with `iv` as a 4-dp fraction, `method` `provider_model_30d`, and tenors 60 and 90 all `null`

#### Scenario: Crude oil futures snapshot
- **WHEN** `GET /volatility/CL?sec_type=future&provider=ibkr` is requested
- **THEN** the provider SHALL resolve the NYMEX front-month contract with at least 7 days to last trade and return its 30-day IV, with `source_instrument` like `CLZ6`

#### Scenario: Tick not received
- **WHEN** no implied volatility tick arrives within the timeout (e.g. GC)
- **THEN** the system SHALL respond with HTTP 404 and `details.reason` `no_iv_data`, and the subscription SHALL be cancelled

#### Scenario: Index history
- **WHEN** `GET /volatility/SPX/history?sec_type=index&provider=ibkr` is requested
- **THEN** the system SHALL return daily points for the last 365 days, with `iv` from the bar closes as 4-dp fractions

#### Scenario: Futures history rejected
- **WHEN** `GET /volatility/ES/history?sec_type=future&provider=ibkr` is requested
- **THEN** the system SHALL respond with HTTP 501 and code `CAPABILITY_NOT_SUPPORTED` without requesting IBKR history

#### Scenario: ric not supported
- **WHEN** `GET /volatility/AAPL?provider=ibkr&ric=AAPLATMIV.U` is requested
- **THEN** the system SHALL respond with HTTP 422

### Requirement: Volatility error mapping
The volatility capability SHALL map upstream outcomes to existing error codes:
- A snapshot where all IV values are empty SHALL raise `DATA_NOT_FOUND` (HTTP 404) with `details.reason` `no_iv_data`. This includes unknown instruments, which LSEG returns as empty rows.
- An empty history SHALL raise `DATA_NOT_FOUND` (HTTP 404) with `details.reason` `no_iv_history`.
- A missing entitlement SHALL raise `PROVIDER_NOT_AVAILABLE` (HTTP 503) with `details.reason = "not_entitled"`.
- Transient errors SHALL be retried and then raise `PROVIDER_CONNECTION_ERROR` (HTTP 503).
- `DATA_VALIDATION_ERROR` SHALL map to HTTP 422.
- `CAPABILITY_NOT_SUPPORTED` SHALL map to HTTP 501.
- These rules SHALL apply to both providers. IBKR "not subscribed" (354/10089) SHALL map to `not_entitled`.

#### Scenario: Unknown instrument
- **WHEN** LSEG returns an all-NaN row for `ZZZZATMIV.U`
- **THEN** the endpoint SHALL respond with HTTP 404, code `DATA_NOT_FOUND` and `details.reason` `no_iv_data`

#### Scenario: Unsupported futures root
- **WHEN** a client calls `GET /volatility/CL?sec_type=future&provider=lseg`
- **THEN** the endpoint SHALL respond with HTTP 404 and `details.reason` `no_iv_data`

#### Scenario: Not entitled
- **WHEN** LSEG reports `UserNotPermission` or an insufficient scope for the instrument
- **THEN** the endpoint SHALL respond with HTTP 503, code `PROVIDER_NOT_AVAILABLE` and `details.reason` `not_entitled`

### Requirement: Volatility MCP tools
When MCP is enabled, the system SHALL expose three tools:
- `get_implied_volatility`, with argument `symbol` and optional `sec_type`, `ric` and `provider`. It SHALL return the serialized `VolatilitySnapshot`.
- `get_implied_volatility_history`, with argument `symbol` and optional `start_date`, `end_date`, `tenor_days`, `sec_type`, `ric` and `provider`. It SHALL return the serialized `VolatilityHistory`.
- `get_implied_volatility_stats`, with argument `symbol` and optional `window`, `tenor_days`, `sec_type`, `ric` and `provider`. It SHALL return the serialized `VolatilityStats`.

#### Scenario: Agent requests IV
- **WHEN** an MCP client calls `get_implied_volatility` with `{"symbol": "aapl"}`
- **THEN** the tool SHALL return the JSON-serialized snapshot for `AAPL` from the default volatility provider

#### Scenario: Agent requests futures IV history
- **WHEN** an MCP client calls `get_implied_volatility_history` with `{"symbol": "ES", "sec_type": "future", "tenor_days": 60}`
- **THEN** the tool SHALL return the 60-day IV history for `ESATMIV`

#### Scenario: Agent requests IV Rank
- **WHEN** an MCP client calls `get_implied_volatility_stats` with `{"symbol": "SPY", "sec_type": "etf"}`
- **THEN** the tool SHALL return the 252-point IV Rank and IV Percentile for `SPYATMIV.U`
