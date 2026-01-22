# Market Open Status Feature

## Overview
The `get_last_price()` method returns an `is_market_open` flag in addition to the price quote, indicating whether the market is currently open.

## Implementation Details

### Model
```python
class PriceQuote(BaseModel):
    symbol: str
    price: Decimal
    currency: str
    timestamp: datetime
    provider: str
    bid: Optional[Decimal] = None
    ask: Optional[Decimal] = None
    volume: Optional[int] = None
    is_market_open: Optional[bool] = None
```

### IBKR Provider

- `_get_trading_hours(contract) -> Optional[tuple[str, str]]`
  - Returns `(trading_hours, time_zone_id)` from Contract Details.
  - `trading_hours` Format (new, IBKR): `YYYYMMDD:HHMM-YYYYMMDD:HHMM;...;YYYYMMDD:CLOSED`
  - Fallback (old): `NYSESTD;0930-1600` including optional CLOSED segments

- `_is_market_open(trading_hours: Optional[str], timezone_id: Optional[str]) -> Optional[bool]`
  - Parses the new date-prefixed format (per day/segment), including `CLOSED` entries
  - Fallback to the old `ZONE;HHMM-HHMM` format
  - Uses IBKR's `timeZoneId` (e.g., `US/Eastern`, `MET`, `Japan`) and maps it to IANA timezones via `zoneinfo` (e.g., `America/New_York`, `Europe/Berlin`, `Asia/Tokyo`)
  - Determines the current time in the exchange timezone and checks if it falls within an open time window

- `_get_market_open_status(contract) -> Optional[bool]`
  - Wrapper that loads `(trading_hours, timeZoneId)` and passes them to `_is_market_open(...)`

### Return Values
- `True` = Market is open
- `False` = Market is closed
- `None` = Status unknown (e.g., no Contract Details or unparseable format)

## Timezones
- Uses the `timeZoneId` provided by IBKR, with robust mapping to IANA timezones.
- Server does not need to run in US/Eastern timezone; calculation is timezone-correct.

## Error Handling
- No exceptions; returns `None` for incomplete data.
- Unexpected formats are logged and treated as `None`.

## Testing
- End-to-end verification script: [scripts/diagnostics/verify_market_open_fix.py](../scripts/diagnostics/verify_market_open_fix.py)
- Example:
```python
quote = await ibkr_provider.get_last_price("AAPL")
print(f"Market open: {quote.is_market_open}")
```

## Status
- Feature active: `/prices/{symbol}/last` returns `is_market_open` as boolean when Contract Details provide `tradingHours`.
