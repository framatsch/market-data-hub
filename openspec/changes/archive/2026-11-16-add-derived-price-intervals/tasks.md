## 1. Interval utilities

- [x] 1.1 Create `app/utils/intervals.py` with `CANONICAL_INTERVALS`, `normalize_interval(raw)` (case, `60m` → `1h`, `1wk` → `1w`) and `select_source_interval(target, native)` (`1w` from `1d`; largest dividing native intraday interval; `None` when not derivable)
- [x] 1.2 Add `bucket_bounds(interval, instant)`: ISO week by UTC calendar date for `1w` (Monday 00:00:00 to Sunday 23:59:59 UTC), clock-aligned `America/New_York` buckets for intraday (the same periods as `current_period_start`)
- [x] 1.3 Add `aggregate_bars(bars, target, source)`: group by bucket (daily sources by `trading_date` from `app/market_hours.py`, no second implementation), build OHLCV, `start`/`end`, `source_interval`
- [x] 1.4 Add `tests/unit/test_intervals.py` covering aliases, source selection per provider, bucket boundaries (DST change, New York midnight vs UTC midnight daily stamps, `start` Monday 02:00Z and 06:00Z in the same week), aggregation values, holiday week and empty bucket

## 2. Model and providers

- [x] 2.1 Add optional `source_interval` to `PriceBar` and to the CSV export in `routes_prices.py`
- [x] 2.2 `base.py`: add `native_intervals: frozenset[str]`
- [x] 2.3 Declare `native_intervals` in `polygon.py`, `schwab.py`, `ibkr.py`, `lseg.py` and `prixe.py` as specified. Prixe maps `1w` to its `1wk`
- [x] 2.4 `lseg.py`: remove the `2m` → `MINUTE` and `15m` → `TEN_MINUTES` mappings
- [x] 2.5 Add a unit test that every provider's `native_intervals` matches its interval mapping and contains `1d`

## 3. Service

- [x] 3.1 `PriceService.get_historical_prices`: normalize the interval as the first step, before the lookup in `history_store_intervals`; pass native intervals through, and reject anything else with `DataValidationError` (details `provider`, `interval`, `native_intervals`, `derived_intervals`) before the provider call
- [x] 3.2 For a derived interval: widen `start`/`end` to bucket bounds, call the provider directly with the source interval (the source's store series is not used), aggregate, and return the buckets overlapping the requested range together with the fetch time of the source call for `meta.data_as_of`
- [x] 3.3 Extend `tests/unit/test_services.py`: Tuesday-to-Thursday weekly request (widened provider call, one full-week bar), range across two weeks, `4h` from `30m`, running week, 422 without provider call (Polygon `30m`, LSEG `2m`), Schwab `30m` and Prixe `1mo` pass-through, fetch time of the source call returned
- [x] 3.4 `app/cache.py`: normalize the interval in the price history key builder and in `_compose_key` before the daily-or-longer and lifetime rules; tests for `1wk`/`1w` sharing a key, `1W` with a day-granular `start`, and `4h` keeping the requested interval
- [x] 3.5 History store: make the store's range loader call the native-or-derived path of the price service; Alembic migration for the nullable `history_series.source_interval`; set it on series creation, rebuild bars with it, reload a series whose source differs
- [x] 3.6 Integration tests with the history store enabled: `1D` is served through the store; `1w` stored for Polygon (first request derives and stores, second needs no provider call, running week not stored, stale on a failed tail); `4h` stored for Schwab; the stored `1d` series is untouched by a derived `1w`; `15m` from LSEG never touches the store; source change reloads the series

## 4. Admin, MCP, docs

- [x] 4.1 `routes_admin.py`: add `native_intervals` and `derived_intervals` to `price_support`; update `admin/src/types.ts` and the provider details view; mark native and derived in the selection of the stored intervals and remove the availability note; extend the admin API test
- [x] 4.2 `app/api/mcp.py`: list the canonical intervals in the `get_historical_prices` tool description and add `source_interval` to the result
- [x] 4.3 Update README, `doc/mcp-guide.md` and `.github/copilot-instructions.md`: canonical intervals, derivation, clock-aligned `4h` buckets, provider limits on source bars, storing derived intervals
- [x] 4.4 Add a CHANGELOG entry including the two breaking points

## 5. Verification

- [x] 5.1 Run the unit test suite and lint
- [x] 5.2 Smoke test against live providers (done: Polygon `1w` derived from `1d`, all 28 closed weeks equal to a manual aggregation, stored with `source_interval` `1d`; LSEG `4h` from `1h` and `15m` from `5m` equal to the store-built series; IBKR `4h` from `1h`)
- [ ] 5.3 Smoke test the remaining combinations: `1h`/`4h` from Schwab for a Tuesday-to-Thursday range compared with native IBKR bars, and `F:ES` weekly bars for the Sunday-evening session
