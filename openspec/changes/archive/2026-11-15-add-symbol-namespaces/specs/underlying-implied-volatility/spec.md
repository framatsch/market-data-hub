## ADDED Requirements

### Requirement: Namespaced volatility symbols
The volatility endpoints (`GET /volatility/{symbol}`, `/history`, `/stats`) and MCP tools (`get_implied_volatility`, `get_implied_volatility_history`, `get_implied_volatility_stats`) SHALL resolve `symbol` and `sec_type` with the central symbol parser (capability `symbol-namespaces`). The `sec_type` parameter SHALL remain optional and SHALL be case-insensitive. The response `symbol` SHALL be the canonical symbol, and the response `sec_type` SHALL be the resolved type. LSEG ATMIV resolution, market validation and IBKR contract selection SHALL operate on the bare root and resolved `sec_type`, exactly as for the equivalent legacy request. An explicit `ric` override SHALL keep working unchanged.

#### Scenario: Future via prefix on LSEG
- **WHEN** a client calls `GET /volatility/F:ES?provider=lseg`
- **THEN** the system queries `ESATMIV` and returns `symbol` `F:ES` and `sec_type` `future`

#### Scenario: Index via prefix on IBKR
- **WHEN** a client calls `GET /volatility/I:SPX/stats?provider=ibkr`
- **THEN** the system computes IV Rank and IV Percentile from the IBKR index history for `SPX` and returns `symbol` `I:SPX`

#### Scenario: Future stats unsupported on IBKR
- **WHEN** a client calls `GET /volatility/F:ES/stats?provider=ibkr`
- **THEN** the system responds with HTTP 501 and error code `CAPABILITY_NOT_SUPPORTED`, as for `sec_type=future`

#### Scenario: MCP future alias
- **WHEN** an MCP client calls `get_implied_volatility_stats` with `{"symbol": "/ES", "provider": "lseg"}`
- **THEN** the result has `symbol` `F:ES` and is computed from `ESATMIV` history

#### Scenario: Equity ticker that equals a futures root stays a stock
- **WHEN** a client calls `GET /volatility/CL`
- **THEN** the request is treated as the stock `CL`, and LSEG market validation applies as before

## MODIFIED Requirements

### Requirement: Volatility error mapping
The volatility capability SHALL map upstream outcomes to existing error codes:
- A snapshot where all IV values are empty SHALL raise `DATA_NOT_FOUND` (HTTP 404) with `details.reason` `no_iv_data`. This includes unknown instruments, which LSEG returns as empty rows.
- An empty history SHALL raise `DATA_NOT_FOUND` (HTTP 404) with `details.reason` `no_iv_history`.
- A missing entitlement SHALL raise `PROVIDER_NOT_ENTITLED` (HTTP 403) as defined by capability `provider-entitlement-errors`.
- Transient errors SHALL be retried and then raise `PROVIDER_CONNECTION_ERROR` (HTTP 503).
- `DATA_VALIDATION_ERROR` SHALL map to HTTP 422.
- `CAPABILITY_NOT_SUPPORTED` SHALL map to HTTP 501.
- These rules SHALL apply to both providers. IBKR "not subscribed" (354/10089) SHALL map to `PROVIDER_NOT_ENTITLED`.

#### Scenario: Unknown instrument
- **WHEN** LSEG returns an all-NaN row for `ZZZZATMIV.U`
- **THEN** the endpoint SHALL respond with HTTP 404, code `DATA_NOT_FOUND` and `details.reason` `no_iv_data`

#### Scenario: Unsupported futures root
- **WHEN** a client calls `GET /volatility/CL?sec_type=future&provider=lseg`
- **THEN** the endpoint SHALL respond with HTTP 404 and `details.reason` `no_iv_data`

#### Scenario: Not entitled
- **WHEN** LSEG reports `UserNotPermission` or an insufficient scope for the instrument
- **THEN** the endpoint SHALL respond with HTTP 403 and code `PROVIDER_NOT_ENTITLED`
