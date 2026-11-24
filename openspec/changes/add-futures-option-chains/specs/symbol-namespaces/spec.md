## MODIFIED Requirements

### Requirement: Per-endpoint namespace support
Each symbol-accepting endpoint SHALL declare the instrument types it serves. A request for any other type SHALL be rejected with HTTP 422 and error code `DATA_VALIDATION_ERROR` before any provider is called. The error details SHALL include the parsed `sec_type` and the supported types. The supported types SHALL be:
- prices (last, history): `stock`, `etf`, `index`, `future`
- volatility (snapshot, history, stats): `stock`, `etf`, `index`, `future`
- option chain: `stock`, `etf`, `index`, `future` (the underlying)
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

#### Scenario: Option chain on a future
- **WHEN** a client calls `GET /options/F:ES/chain?provider=ibkrweb&expiry=2026-12-18`
- **THEN** the namespace check passes and the provider-level support check of `ibkrweb` decides

#### Scenario: Option quote on a future
- **WHEN** a client calls `GET /options/F:ES/quote/ESZ6`
- **THEN** the system responds with HTTP 422 and error code `DATA_VALIDATION_ERROR` without calling a provider
