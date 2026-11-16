## ADDED Requirements

### Requirement: Data timestamp in market data responses
JSON responses of `GET /options/{symbol}/chain`, `GET /prices/{symbol}/history`, `GET /volatility/{symbol}`, `GET /volatility/{symbol}/history` and `GET /volatility/{symbol}/stats` SHALL contain `meta.data_as_of`: the UTC time, in ISO 8601 with offset, at which MDH obtained the data from the provider. CSV responses of these endpoints SHALL carry the same value in the header `X-MDH-Data-As-Of`. The `data` part of the responses SHALL be unchanged.

#### Scenario: Live answer
- **WHEN** an option chain is loaded from the provider at 14:30:05 UTC
- **THEN** the response contains `meta.data_as_of` `…T14:30:05…+00:00`

#### Scenario: CSV
- **WHEN** the same chain is requested with `format=csv`
- **THEN** the response has the header `X-MDH-Data-As-Of` and the CSV body has no additional column

### Requirement: Data timestamp survives the response cache
A response served from the response cache SHALL carry the `meta.data_as_of` (or `X-MDH-Data-As-Of`) of the original provider call, not the time of the cache hit.

#### Scenario: Cache hit ten minutes later
- **WHEN** a chain loaded at 14:30:05 UTC is requested again at 14:40:00 UTC and answered with `X-FastAPI-Cache: HIT`
- **THEN** `meta.data_as_of` is still `…T14:30:05…+00:00`

#### Scenario: Forced refresh
- **WHEN** the request carries `Cache-Control: no-cache`
- **THEN** `meta.data_as_of` is the time of the new provider call

### Requirement: Data timestamp of stored history
For responses built from the history store, `meta.data_as_of` SHALL be the time of the last successful provider call for the series. A response served under the provider-failure rule SHALL keep that earlier time and additionally carry `meta.stale` `true`; when the bars come from another provider's series, the time SHALL be that series' last successful provider call.

#### Scenario: Weekend request
- **WHEN** a price series was last synchronised on Friday 21:10 UTC and daily history is requested on Sunday without a provider call
- **THEN** `meta.data_as_of` is Friday 21:10 UTC

#### Scenario: Provider outage
- **WHEN** stored bars are served because the provider timed out
- **THEN** `meta.data_as_of` is the time of the last successful synchronisation and `meta.stale` is `true`
