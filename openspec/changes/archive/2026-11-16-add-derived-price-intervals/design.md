## Context

This change is implemented after `add-market-history-store`. `PriceService.get_historical_prices` then routes an interval listed in the provider's `history_store_intervals` (out of `1h`, `4h`, `1d`, `1w`) through the history store, returns the fetch time alongside the bars (`meta.data_as_of`), and passes the request interval straight to the provider. The store keeps what the service returns and cannot make an interval available. Each provider has its own interval mapping and raises its own error for an unmapped interval. Providers return `list[PriceBar]` with `start`, `end`, OHLC and `volume`. Most providers set `end = start`.

Daily bar timestamps differ between providers: Polygon stamps a daily bar at midnight New York time, the others at midnight UTC. In both conventions the UTC calendar date of `start` is the trading date. The history store uses the same rule and provides it as `trading_date` in `app/market_hours.py`.

Native `1h` bars at Polygon, IBKR and LSEG are aligned to the clock hour (10:00, 11:00, ...). With RTH filtering, the first bar of a day starts at 09:30 or 10:00, depending on the provider.

## Goals / Non-Goals

**Goals:**
- The canonical intervals up to `1w` work against every price provider.
- A derived bar always covers its complete bucket, whatever range the client asked for.
- The derivation lives in one place and needs no provider-specific code.

**Non-Goals:**
- Deriving `1d` from intraday bars, or monthly and longer bars.
- Filling gaps: a bucket without source bars yields no bar. Nothing is interpolated.
- Making native bars of different providers align with each other.
- Raising provider lookback or bar-count limits, or paging provider requests.

## Decisions

### Derivation in `PriceService`, declaration in the provider
Each provider declares `native_intervals: frozenset[str]` in canonical notation. `PriceService` normalizes the interval, picks a source interval, widens the range, calls the provider with the source interval and aggregates. The pure logic (aliases, source selection, bucket boundaries, aggregation) goes into `app/utils/intervals.py`.

Alternative: derive inside each provider. Rejected, because five providers would repeat the same logic.

Alternative: map more intervals natively where the provider API allows it (Polygon accepts any multiplier, IBKR has `4 hours`). Rejected for now: native bucket boundaries differ per provider (Polygon weeks start on Sunday), and the generic path is needed anyway for Schwab and LSEG. A provider can still add an interval to `native_intervals` later.

### Source interval selection
- `1w` is derived from `1d` only.
- An intraday target is derived from the largest native intraday interval whose length divides the target length.
- `1d` is never a target, and intraday bars are never a source for `1w`.
- Only canonical intervals are targets. Any native intraday interval can be a source, canonical or not (Schwab `30m`).

The largest dividing interval keeps the number of fetched bars low. `1m`, `5m` and `1d` are native everywhere. Resulting sources for the rest:

| Provider | `15m` | `1h` | `4h` | `1w` |
|----------|-------|------|------|------|
| Polygon  | `5m` | native | `1h` | `1d` |
| Schwab   | native | `30m` | `30m` | native |
| IBKR     | native | native | `1h` | native |
| LSEG     | `5m` | native | `1h` | native |
| Prixe    | native | native | `1h` | native |

The canonical set is deliberately small: `2m`, `10m` and `30m` are not needed across providers. They stay available where a provider maps them natively.

LSEG's mapping of `2m` to 1-minute bars and `15m` to 10-minute bars is removed. LSEG's native set is `1m`, `5m`, `30m`, `1h`, `1d`, `1w`.

### Derivation below the history store
The store sits above the derivation. For a stored interval the store plans the ranges its series misses (full load, backfill, tail with overlap) and asks the price service for each; the price service answers natively or derived. The store then keeps the closed bars in the series of the requested interval. Nothing in the store knows how a bar was produced, except that the series records `source_interval`, so rebuilt bars carry it.

Consequences:
- Every storable interval works for every provider: `1w` for Polygon, `1h` and `4h` for Schwab, `4h` everywhere. The Admin UI marks them as derived instead of warning that they may be unavailable.
- Coverage, tail throttle, overlap comparison and stale serving apply to derived series unchanged. A split shows in the derived bars of the overlap as it does in native ones.
- The source bars are always loaded from the provider. A derived `1w` does not read the stored `1d` series of the same provider, and does not write it. The two series stay independent, each with its own coverage.
- A derived bar is closed by the rule of its own interval: a weekly bar when its Friday is closed, a `4h` bar when its clock-aligned period has ended. The store's periods and the derivation's buckets are the same clock-aligned `America/New_York` periods.
- When the source of a stored series changes (an interval becomes native, or another source interval is selected), the stored bars may have other boundaries. The series is reloaded on the next synchronisation.
- `15m` is derived for Polygon and LSEG but is not storable, so it never touches the store.

The interval is normalized first, so `1D` reaches the store like `1d`, and the cache key builder sees `1w` for `1wk` or `1W`.

Alternative: aggregate `1w` from the stored `1d` series and `4h` from the stored `1h` series, without a provider call. Rejected for now: it couples two series (the weekly answer would depend on the coverage and revision state of the daily one), and it only works where the source interval is stored too. It can follow as its own change.

### Bucket boundaries
- **Weekly**: a bucket is an ISO week, Monday to Sunday. A daily bar belongs to the week of its trading date, the UTC calendar date of its `start` (`trading_date`). This works for both daily timestamp conventions. The requested `start` and `end` are assigned to a week by their UTC calendar date as well.
- **Intraday**: buckets are aligned to the clock in `America/New_York`, counted from midnight. `1h` buckets start at 09:00, 10:00, ...; `4h` buckets at 00:00, 04:00, 08:00, 12:00, 16:00, 20:00. A source bar belongs to the bucket that contains its `start`.

Clock alignment matches the native `1h` bars of Polygon, IBKR and LSEG, so a derived `1h` bar from Schwab looks like a native one elsewhere. It also means any clock-aligned source interval fits every target.

Alternative: anchor intraday buckets at the session open (09:30 to 13:30, 13:30 to 16:00 for `4h`), as charting tools do. Rejected: hourly source bars start on the full hour and cannot be split at 09:30 or 13:30. It would force 30-minute or smaller sources and several times more fetched bars. With RTH filtering, the clock-aligned `4h` bars of a US session cover 09:30 to 12:00 and 12:00 to 16:00.

### Range widening and result selection
Before the provider call, `start` is moved back to the start of its bucket and `end` forward to the end of its bucket. After aggregation, the service returns every bucket that overlaps the requested range. The current, unfinished bucket is returned with the bars available so far, as native weekly bars behave.

A weekly request from Tuesday to Thursday therefore fetches Monday 00:00:00 to Sunday 23:59:59 UTC and returns one bar for the whole week.

Weekly widening uses UTC dates, not New York time, because the response cache reduces `start` and `end` of daily-or-longer history to their UTC date and the store moves a weekly `start` to the Monday of its UTC week. With New York time, `start` Monday 02:00Z (Sunday evening in New York) would add the previous week and `start` Monday 06:00Z would not, under the same cache key. Intraday widening stays on the New York clock; intraday keys keep the full values.

The store asks for partial ranges (a tail from a few bars before `covered_to`). Widening makes each of them whole buckets, so a stored derived bar is always complete.

### Aggregation
For the source bars of one bucket, ordered by `start`:
- `open` of the first bar, `close` of the last bar, highest `high`, lowest `low`, summed `volume`
- `start` of the first bar, `end` of the last bar
- `symbol`, `provider` and `source_instrument` of the first bar
- `source_interval` set to the source interval

The bar `start` is the first source bar, not the bucket boundary. A week with a Monday holiday starts on Tuesday, and an RTH `4h` bar starts at 09:30. This is how native bars are stamped, and it avoids converting between the providers' daily timestamp conventions.

### Unsupported intervals
`PriceService` rejects an interval that is neither native nor derivable for the provider with `DataValidationError` (HTTP 422) before the provider is called. The details list `native_intervals` and `derived_intervals`. A native interval outside the canonical set, such as Prixe `1mo` or Schwab `30m`, stays allowed for that provider and is passed through.

### Caching
Cache keys and TTL rules use the requested interval, never the source interval. `interval_parts` already parses `4h` and `1w`, but it is case-sensitive and the key holds the raw query value. The key builder and `_compose_key` therefore normalize the interval first: `1wk` and `1w` share one entry, and `1W` gets the day-granular `start` and `end` of daily-or-longer history.

## Risks / Trade-offs

- [Derived requests fetch more source bars] → Source selection picks the largest dividing interval. Provider limits still apply: LSEG caps intraday requests at 1000 bars, Polygon returns 5000 aggregates by default, Schwab limits intraday lookback. A long `4h` range can come back truncated. Mitigation: document the limits. Paging is out of scope.
- [Derived `4h` bars differ from charting tools that anchor at 09:30] → Documented. `source_interval` marks the bars as derived.
- [Sunday-evening futures bars] → A daily bar of `F:ES` stamped on a Sunday falls into the week that ends that Sunday. Providers stamp continuous-future daily bars by trade date (Monday), so this should not occur. Verify in the smoke test.
- [A stored derived series was built with another source] → The series records `source_interval`; a mismatch reloads it. Series stored before this change have no source and are native.
- [Tail of a derived intraday series costs more source bars] → The tail covers `HISTORY_STORE_OVERLAP_BARS` target bars, e.g. five `4h` bars from 40 `30m` bars at Schwab. Small next to a full load.
- [Volume semantics] → Summed volume is exact for trade bars. Index bars with zero volume stay zero.

## Migration Plan

Additive, except for the two breaking points in the proposal. One schema migration adds the nullable column `history_series.source_interval`; existing rows stay null (native). No data migration. Cached history entries for LSEG `15m` expire through their TTL, or are flushed once after deployment.
