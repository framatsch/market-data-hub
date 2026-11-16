# derived-price-intervals Specification

## Purpose
Canonical price intervals and the aggregation of coarser or missing intervals from a provider's native bars, with the source interval marked on each bar.
## Requirements
### Requirement: Canonical interval set
Historical price requests SHALL accept the canonical intervals `1m`, `5m`, `15m`, `1h`, `4h`, `1d` and `1w`. The aliases `60m` and `1wk` SHALL be normalized to `1h` and `1w`. Interval matching SHALL be case-insensitive. Every enabled price provider SHALL answer every canonical interval, natively or derived.

The interval SHALL be normalized before any other decision that depends on it: the lookup in the provider's `history_store_intervals` of `market-history-store`, the response-cache key, and the choice between the native and the derived path.

#### Scenario: Alias
- **WHEN** a client requests `GET /prices/AAPL/history?interval=1wk&provider=ibkr`
- **THEN** the request is handled as `interval=1w`

#### Scenario: Upper-case daily interval uses the history store
- **WHEN** the history store is enabled, `1d` is stored for the provider, and a client requests `interval=1D`
- **THEN** the request is served through the store exactly as `interval=1d`

#### Scenario: Same interval at every provider
- **WHEN** a client requests `interval=4h` from Polygon, Schwab, IBKR, LSEG and Prixe
- **THEN** each provider returns 4-hour bars

### Requirement: Native interval declaration
Every price provider SHALL declare `native_intervals`: the intervals for which the hub requests bars of exactly that length from the provider. A provider SHALL NOT answer an interval with bars of another length. The declared sets SHALL be:

| Provider | `native_intervals` |
|----------|--------------------|
| Polygon  | `1m` `5m` `1h` `1d` |
| Schwab   | `1m` `5m` `10m` `15m` `30m` `1d` `1w` |
| IBKR     | `1m` `2m` `5m` `15m` `30m` `1h` `1d` `1w` |
| LSEG     | `1m` `5m` `30m` `1h` `1d` `1w` |
| Prixe    | `1m` `2m` `5m` `15m` `30m` `1h` `90m` `1d` `5d` `1w` `1mo` `3mo` |

A native interval outside the canonical set (e.g. Schwab `30m`, Prixe `1mo`) SHALL be passed through unchanged for that provider. It SHALL NOT be a target of derivation.

#### Scenario: Native interval is passed through
- **WHEN** a client requests `interval=1h` from Polygon
- **THEN** Polygon is called with its hourly interval and the bars are returned unchanged with `source_interval` null

#### Scenario: LSEG no longer substitutes intervals
- **WHEN** a client requests `interval=15m` from LSEG
- **THEN** the response contains 15-minute bars derived from `5m`, not 10-minute bars

### Requirement: Source interval selection
When the requested canonical interval is not in the provider's `native_intervals`, `PriceService` SHALL derive it from a source interval of the same provider:
- `1w` SHALL be derived from `1d`.
- `15m`, `1h` and `4h` SHALL be derived from the largest native intraday interval whose length divides the requested length. The source MAY be a native interval outside the canonical set.
- `1d` SHALL NOT be derived. Intervals longer than `1w` and intervals outside the canonical set SHALL NOT be derived.

The source bars SHALL be loaded from the provider directly. The history store series of the source interval SHALL be neither read nor written by a derivation.

#### Scenario: Weekly from daily
- **WHEN** a client requests `interval=1w` from Polygon
- **THEN** Polygon is called with `1d` and the daily bars are aggregated to weekly bars

#### Scenario: Source series is not used
- **WHEN** the history store holds a Polygon `1d` series for `AAPL` and a client requests `interval=1w` from Polygon for a range the weekly series does not cover
- **THEN** Polygon is called with `1d` for the widened range, and no row or coverage of the `1d` series is read or changed

#### Scenario: Largest dividing interval
- **WHEN** a client requests `interval=4h` from Schwab, whose native intraday intervals are `1m`, `5m`, `10m`, `15m` and `30m`
- **THEN** Schwab is called with `30m`

#### Scenario: Hourly from half-hourly
- **WHEN** a client requests `interval=1h` from Schwab
- **THEN** Schwab is called with `30m` and two source bars form one hourly bar

### Requirement: Bucket boundaries
Derived bars SHALL be grouped into fixed buckets:
- Weekly buckets SHALL be ISO weeks from Monday to Sunday. A daily source bar SHALL belong to the week of its trading date, which is the UTC calendar date of its `start` (the same rule as in `market-history-store`). The requested `start` and `end` SHALL be assigned to a week by their UTC calendar date; their time of day SHALL have no effect.
- Intraday buckets SHALL be aligned to the clock in `America/New_York`, counted from midnight. A source bar SHALL belong to the bucket that contains its `start`.

#### Scenario: Four-hour buckets in a regular session
- **WHEN** `interval=4h` is derived from RTH hourly bars of one trading day
- **THEN** the day yields two bars: one from the source bars starting between 08:00 and 12:00 New York time, one from those starting between 12:00 and 16:00

#### Scenario: Daily bar stamped at New York midnight
- **WHEN** a daily source bar has `start` 2026-11-09T05:00:00Z (Monday, New York midnight)
- **THEN** it belongs to the week of Monday 2026-11-09

#### Scenario: Daily bar stamped at UTC midnight
- **WHEN** a daily source bar has `start` 2026-11-09T00:00:00Z (Sunday evening in New York)
- **THEN** it belongs to the week of Monday 2026-11-09

### Requirement: Range widening to whole buckets
For a derived interval, `PriceService` SHALL widen the requested range before calling the provider: `start` SHALL move back to the start of its bucket and `end` forward to the end of its bucket. For `1w` the widened range SHALL run from Monday 00:00:00 UTC of the week of `start` to Sunday 23:59:59 UTC of the week of `end`, so that two requests with the same response-cache key return the same bars. The response SHALL contain every bucket that overlaps the requested range, each aggregated from all source bars of that bucket. The bucket of the current time SHALL be returned with the source bars available so far.

#### Scenario: Weekly request inside one week
- **WHEN** a client requests `interval=1w` from Polygon with `start` Tuesday 2026-11-03 and `end` Thursday 2026-11-05
- **THEN** Polygon is asked for daily bars from Monday 2026-11-02 to Sunday 2026-11-08, and the response contains one bar aggregated from Monday to Friday

#### Scenario: Range across two weeks
- **WHEN** a client requests `interval=1w` with `start` Thursday 2026-11-05 and `end` Tuesday 2026-11-10
- **THEN** the response contains two bars, each covering its complete week

#### Scenario: Time of day does not change the weeks
- **WHEN** a client requests `interval=1w` once with `start` 2026-11-09T02:00:00Z and once with `start` 2026-11-09T06:00:00Z (Sunday evening and Monday morning in New York)
- **THEN** both responses start with the week of Monday 2026-11-09 and contain the same bars

#### Scenario: Intraday request inside a bucket
- **WHEN** a client requests `interval=4h` with `start` 13:00 and `end` 14:00 New York time on one trading day
- **THEN** the source bars from 12:00 to 16:00 are fetched and one bar for that bucket is returned

#### Scenario: Running week
- **WHEN** a client requests `interval=1w` on a Wednesday with `end` today
- **THEN** the last bar is aggregated from Monday to Wednesday of the current week

### Requirement: Aggregation
A derived bar SHALL be built from the source bars of one bucket, ordered by `start`:
- `open` SHALL be the open of the first bar and `close` the close of the last bar.
- `high` SHALL be the highest high and `low` the lowest low.
- `volume` SHALL be the sum of the volumes.
- `start` SHALL be the `start` of the first bar and `end` the `end` of the last bar.
- `symbol`, `provider` and `source_instrument` SHALL be taken from the source bars.

A bucket without source bars SHALL yield no bar. No values SHALL be interpolated. RTH filtering applies to the source bars, so a derived intraday bar without `extended_hours=true` SHALL contain only regular-session data.

#### Scenario: Weekly bar values
- **WHEN** a week has five daily bars with opens 10, 11, 12, 13, 14, highs 12, 15, 13, 14, 16, lows 9, 10, 11, 12, 13, closes 11, 12, 13, 14, 15 and volumes of 100 each
- **THEN** the weekly bar has open 10, high 16, low 9, close 15 and volume 500

#### Scenario: Holiday week
- **WHEN** a week has no daily bar for Monday
- **THEN** the weekly bar is aggregated from Tuesday to Friday and its `start` is Tuesday's bar start

#### Scenario: Week without data
- **WHEN** the provider returns no daily bars for a week in the requested range
- **THEN** the response contains no bar for that week

### Requirement: Source interval on bars
`PriceBar` SHALL have an optional field `source_interval`. It SHALL be the source interval for derived bars and null for native bars. The field SHALL be included in JSON responses, MCP results and the CSV export.

#### Scenario: Derived bar is marked
- **WHEN** a client requests `interval=1w` from Polygon
- **THEN** every bar has `source_interval` `1d`

### Requirement: Derived bars in the history store
A derived interval that is listed in the provider's `history_store_intervals` SHALL use the history store like a native one: the store asks the price service for the ranges its series does not cover, the price service derives the bars for these ranges, and the closed derived bars SHALL be stored in the series of the requested interval. The coverage, tail, revision and provider-failure rules of `market-history-store` SHALL apply unchanged. A derived bar SHALL be closed under the rule of its own interval, not of its source interval. A derived interval that is not storable (`15m`) SHALL NOT use the store.

#### Scenario: Derived weekly bars are stored
- **WHEN** `1w` is stored for Polygon and `interval=1w` is requested from Polygon twice while the market is settled, with the response cache entry removed in between
- **THEN** the first request calls Polygon with `1d`, the second calls no provider, and both return the same bars with `source_interval` `1d`

#### Scenario: Running week of a derived series
- **WHEN** `1w` is stored for Polygon and weekly history is requested on Wednesday
- **THEN** the bar of the current week is aggregated from Monday to Wednesday, returned, and not stored

#### Scenario: Derived four-hour bars at a provider without hourly bars
- **WHEN** `4h` is stored for Schwab and `interval=4h` is requested from Schwab
- **THEN** Schwab is called with `30m` for the ranges the `4h` series does not cover, and the closed `4h` bars are stored

#### Scenario: Source call fails with stored bars
- **WHEN** `1w` is stored for Polygon, the weekly series covers the requested closed weeks, and Polygon times out on the tail
- **THEN** the response is `200` with the stored weekly bars and `meta.stale` `true`

#### Scenario: Derived interval that is not storable
- **WHEN** a client requests `interval=15m` from LSEG
- **THEN** the bars are derived from `5m` and the store is neither read nor written

### Requirement: Data timestamp of derived responses
For a derived response that is not built from the history store, `meta.data_as_of` (and `X-MDH-Data-As-Of` for CSV) as defined by `response-data-timestamp` SHALL be the time at which MDH obtained the source bars from the provider. A response built from a stored derived series SHALL follow the rule for stored history.

#### Scenario: Derived bars from the provider
- **WHEN** a client requests `interval=15m` from LSEG and the `5m` source bars are loaded at 14:30:05 UTC
- **THEN** the response contains `meta.data_as_of` `…T14:30:05…+00:00`

### Requirement: Unsupported interval
When the requested interval is neither in the provider's `native_intervals` nor derivable, `PriceService` SHALL respond with HTTP 422 `VALIDATION_ERROR` without calling the provider. The details SHALL include `provider`, `interval`, `native_intervals` and `derived_intervals`.

#### Scenario: Unknown interval
- **WHEN** a client requests `interval=3h` from Polygon
- **THEN** the system responds with HTTP 422 and lists Polygon's native and derived intervals, and Polygon is not called

#### Scenario: Monthly at a provider without it
- **WHEN** a client requests `interval=1mo` from Schwab
- **THEN** the system responds with HTTP 422, because monthly bars are not derived

#### Scenario: Non-canonical interval is not derived
- **WHEN** a client requests `interval=30m` from Polygon
- **THEN** the system responds with HTTP 422, although `30m` could be computed from `5m`

#### Scenario: Non-canonical native interval
- **WHEN** a client requests `interval=30m` from Schwab or `interval=1mo` from Prixe
- **THEN** the provider is called with that interval as before

### Requirement: Intervals in the admin API
`GET /api/admin/providers` SHALL include `native_intervals` and `derived_intervals` in `price_support` for every price provider. `derived_intervals` SHALL be the canonical intervals that are not native. The Admin UI SHALL display both lists in the provider details. The selection of `history_store_intervals` in the provider details SHALL mark each storable interval as native or derived for that provider, and SHALL no longer state that an interval may be unavailable, because every storable interval is canonical.

#### Scenario: Admin shows Polygon intervals
- **WHEN** an admin opens the provider details for Polygon
- **THEN** the native intervals `1m`, `5m`, `1h`, `1d` and the derived intervals `15m`, `4h`, `1w` are shown

#### Scenario: Stored interval selection for Polygon
- **WHEN** an admin opens the stored interval selection for Polygon
- **THEN** `1h` and `1d` are marked native, and `4h` and `1w` are marked derived

