## Context

Market data providers differ in how they handle extended trading hours (pre-market, after-hours) for historical intraday prices. Some providers (like IBKR) explicitly allow filtering via the API, while others (like Polygon aggregates) return all data and leave filtering to the client. We want to standardize the `/prices/{symbol}/historical` endpoint so that it only returns Regular Trading Hours (RTH) by default, while still providing the option to request extended hours data.

## Goals / Non-Goals

**Goals:**
- Provide a consistent, predictable historical pricing behavior across all providers, defaulting to RTH.
- Add an explicit `extended_hours` boolean query parameter to the historical prices endpoint.
- Ensure all provider implementations (IBKR, Polygon, LSEG) respect this flag.

**Non-Goals:**
- Handling RTH filtering for daily (`1d`) or larger intervals, as these typically span entire trading days and the RTH concept applies specifically to intraday timestamps.
- Adjusting market status or streaming endpoints; this change is strictly for historical price data.

## Decisions

1. **Endpoint Signature Update**
   - We will add `extended_hours: bool = False` to the `/prices/{symbol}/historical` route. This ensures backward compatibility for callers not sending the parameter, while enforcing the new RTH default behavior.
2. **Provider Implementations**
   - **IBKR**: Pass `useRTH=1` (if `extended_hours=False`) or `useRTH=0` (if `extended_hours=True`) to `reqHistoricalDataAsync`.
   - **Polygon**: Since Polygon aggregates lack a native RTH filter, we will filter the returned `PriceBar` list in the provider code by checking if the timestamp falls between 09:30 and 16:00 US/Eastern (adjusting for timezones).
   - **LSEG**: We will check if the Refinitiv SDK `historical_pricing` definitions support a session filter natively. If not, we will apply the same post-processing timestamp filter as Polygon.
3. **Filtering Utility**
   - For providers requiring post-processing (Polygon, LSEG), we will introduce a helper function `_filter_rth(bars: List[PriceBar]) -> List[PriceBar]` that checks if the timestamp is within regular market hours (Monday-Friday, 09:30-16:00 ET). Note: Holidays are ignored in this simple filter unless explicitly provided, as the API simply won't return data for closed days anyway.

## Risks / Trade-offs

- **Risk: Timezone complexities in post-processing**
  - *Mitigation*: Ensure that the timestamp filtering utility explicitly localizes the `PriceBar.start` time to `America/New_York` before checking the 09:30 - 16:00 boundary.
- **Risk: Breaking change for users expecting extended hours**
  - *Mitigation*: The behavior change is clearly documented in the CHANGELOG. The API response shape remains identical, preventing hard crashes in downstream consumers, though the dataset will be smaller.
