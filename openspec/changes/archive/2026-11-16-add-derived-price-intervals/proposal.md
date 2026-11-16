## Why

Each price provider maps only a subset of bar intervals, and the subsets differ:

| Provider | Mapped natively today | Missing from `1m` `5m` `15m` `1h` `4h` `1d` `1w` |
|----------|-----------------------|---------|
| Polygon  | `1m` `5m` `1h` `1d` | `15m` `4h` `1w` |
| Schwab   | `1m` `5m` `10m` `15m` `30m` `1d` `1w` | `1h` `4h` |
| IBKR     | `1m` `2m` `5m` `15m` `30m` `1h` `1d` `1w` | `4h` |
| LSEG     | `1m` `5m` `30m` `1h` `1d` `1w` | `15m` `4h` |
| Prixe    | `1m` `2m` `5m` `15m` `30m` `1h` `90m` `1d` `5d` `1w` (as `1wk`) `1mo` `3mo` | `4h` |

A client that asks Polygon for weekly bars or Schwab for hourly bars gets a provider error, although the bars can be computed from smaller bars the provider does deliver. LSEG is worse: it answers `2m` with 1-minute bars and `15m` with 10-minute bars, without saying so.

The goal is that the same set of intervals, up to weekly, works against every price provider.

## What Changes

- Define one canonical interval set for historical prices: `1m`, `5m`, `15m`, `1h`, `4h`, `1d`, `1w`. `60m` and `1wk` are accepted as aliases for `1h` and `1w`. Every price provider answers all seven.
- Each price provider declares the intervals it delivers natively (`native_intervals`). Native intervals outside the canonical set, such as Schwab `30m` or Prixe `1mo`, keep working for that provider only.
- When a requested canonical interval is not native, `PriceService` derives it: it fetches bars of a smaller native interval and aggregates them (first open, highest high, lowest low, last close, summed volume).
  - `1w` is derived from `1d`.
  - `15m`, `1h` and `4h` are derived from the largest native intraday interval that divides them, e.g. `4h` from `1h`, `1h` from `30m`.
  - Weekly is the largest derived interval. `1d` is never derived, and monthly bars are not derived.
- The requested range is widened to whole buckets before the provider is called. A weekly request from Tuesday to Thursday fetches the daily bars from Monday to Sunday of that week and returns one bar for the complete week.
- Derived bars carry a new optional `source_interval` field (e.g. `1d`), so clients can tell derived bars from native ones.
- An interval that is neither native nor derivable is rejected before any provider call with HTTP 422 and the list of supported intervals.
- The admin API and UI show the native and derived intervals per provider.
- Derived bars of a storable interval (`1h`, `4h`, `1w`) go into the history store like native ones when the interval is listed in the provider's `history_store_intervals`. With this change every storable interval can be switched on for every provider. Stored series record their `source_interval`.
- Response-cache keys of price history contain the normalized interval, so `1wk` and `1w` (or `1D` and `1d`) share one entry and one set of rules.
- **BREAKING**: LSEG `15m` returns real 15-minute bars (derived from `5m`) instead of 10-minute bars. LSEG `2m` is rejected with 422 instead of returning 1-minute bars.
- **BREAKING**: An unsupported interval returns 422 `VALIDATION_ERROR` from the service instead of a provider-specific `ProviderError`.

## Capabilities

### New Capabilities
- `derived-price-intervals`: The canonical interval set, the per-provider native interval declaration, the derivation rules (source selection, bucket boundaries, range widening, aggregation), `source_interval` on bars, and the admin exposure.

### Modified Capabilities
- `response-caching`: price history keys contain the normalized interval; the day-granular key rule and the lifetime rule act on it.
- `market-history-store`: a stored price series records its `source_interval` and is reloaded when it changes.

RTH filtering (`historical-prices`) keeps working unchanged, because it acts on the source bars.

## Dependencies

This change builds on `add-market-history-store`, which is implemented first. It uses the store's per-provider `history_store_intervals`, the service result with fetch time (`meta.data_as_of`), the day-granular cache keys for daily-or-longer history and the `trading_date` helper introduced there.

## Impact

- **New**: `app/utils/intervals.py` (canonical set, aliases, bucket boundaries, aggregation) and tests.
- **Service**: `app/services/price_service.py` normalizes the interval before the store routing, selects the source interval, widens the range and aggregates. The history store calls this path for the ranges it misses.
- **Store**: Alembic migration for `history_series.source_interval`; `app/store/` rebuilds bars with it.
- **Cache**: `app/cache.py` key builder and `_compose_key` use the normalized interval.
- **Providers**: `base.py` (`native_intervals`), `polygon.py`, `schwab.py`, `ibkr.py`, `lseg.py`, `prixe.py` (declaration; LSEG mapping fix).
- **Models**: optional `source_interval` on `PriceBar`, included in the CSV export.
- **Admin**: `routes_admin.py` (`price_support` gains the interval lists), `admin/src` provider details.
- **MCP/Docs**: interval description of `get_historical_prices`, README, `doc/mcp-guide.md`.
- **Provider load**: a derived request fetches more source bars than the result contains (a year of `4h` from `1h` is about 1,750 source bars). Provider lookback and bar-count limits apply to the source interval.
- No new dependencies.
