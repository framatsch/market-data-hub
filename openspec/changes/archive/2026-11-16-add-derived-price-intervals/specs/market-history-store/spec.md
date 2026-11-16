## ADDED Requirements

### Requirement: Source interval of a stored price series
A stored price series SHALL record `source_interval`: null when its bars are loaded natively, otherwise the interval they are derived from as defined by `derived-price-intervals`. Bars rebuilt from the store SHALL carry the `source_interval` of their series. When the source the price service would use for a series differs from the recorded one, the series SHALL be reloaded from the provider before it is served, and the new source SHALL be recorded. Series stored before this capability SHALL count as native.

#### Scenario: Stored derived bars keep their mark
- **WHEN** `1w` is stored for Polygon and weekly history is answered from the store without a provider call
- **THEN** every bar has `source_interval` `1d`

#### Scenario: Stored native bars
- **WHEN** `1d` history is answered from the store
- **THEN** every bar has `source_interval` null

#### Scenario: Interval becomes native
- **WHEN** a provider's `1w` series was stored as derived from `1d` and `1w` is later added to that provider's `native_intervals`
- **THEN** the next weekly request reloads the series with native bars, and the bars have `source_interval` null
