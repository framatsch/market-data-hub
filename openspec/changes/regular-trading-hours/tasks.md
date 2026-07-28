## 1. Provider Interfaces and API Endpoints

- [x] 1.1 Update `/prices/{symbol}/historical` in `app/api/routes_prices.py` to accept `extended_hours: bool = False`.
- [x] 1.2 Update `BasePriceProvider.get_historical_prices` signature in `app/providers/base.py` to accept `extended_hours: bool = False`.

## 2. Implementation: IBKR

- [x] 2.1 Update `IBKRProvider.get_historical_prices` signature in `app/providers/ibkr.py`.
- [x] 2.2 Pass `useRTH=1` when `extended_hours=False` (and `useRTH=0` otherwise) to the `reqHistoricalDataAsync` call.

## 3. Implementation: Polygon

- [x] 3.1 Update `PolygonProvider.get_historical_prices` signature in `app/providers/polygon.py`.
- [x] 3.2 Implement a `_filter_rth(bars: List[PriceBar]) -> List[PriceBar]` helper (either locally or in a shared utils module).
- [x] 3.3 Apply `_filter_rth` in Polygon if `extended_hours=False` and the requested interval is intraday (`1m`, `5m`, `1h`).

## 4. Implementation: LSEG

- [x] 4.1 Update `LSEGProvider.get_historical_prices` signature in `app/providers/lseg.py`.
- [x] 4.2 Investigate session filters for LSEG SDK. If unavailable, apply the same `_filter_rth` helper to the fetched dataframe/bars if `extended_hours=False` and interval is intraday.

## 5. Testing

- [x] 5.1 Update unit tests in `tests/unit/test_ibkr_historical.py` to assert `useRTH` behaves correctly with the new flag.
- [x] 5.2 Add unit tests for the `_filter_rth` timestamp logic (especially regarding timezone conversion to US/Eastern).
- [x] 5.3 Update generic API tests in `tests/unit/test_api.py` to pass or omit the new `extended_hours` query parameter.
## 6. Implementation: Schwab

- [x] 6.1 Update `SchwabProvider.get_historical_prices` signature in `app/providers/schwab.py` to accept `extended_hours: bool = True`.
- [x] 6.2 Pass `need_extended_hours_data=extended_hours` to `easy_client` call.

## 7. Implementation: Prixe

- [x] 7.1 Update `PrixeProvider.get_historical_prices` signature in `app/providers/prixe.py` to accept `extended_hours: bool = True`.
- [x] 7.2 Implement `_filter_rth(bars: List[PriceBar]) -> List[PriceBar]` helper.
- [x] 7.3 Apply `_filter_rth` in Prixe if `extended_hours=False` and the requested interval is intraday (`1m`, `5m`, `1h`, etc.).
