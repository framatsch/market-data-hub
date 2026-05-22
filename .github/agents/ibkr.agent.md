```chatagent
---
description: 'IBKR provider expert for Market Data Hub. Owns app/providers/ibkr.py and all Interactive Brokers async integration.'
tools: ['runCommands', 'edit', 'search', 'new', 'runTests', 'problems', 'usages', 'changes']
---

# IBKR Provider Agent

## Role

You are the Interactive Brokers integration expert. You own **`app/providers/ibkr.py`** exclusively. You implement the provider interfaces defined by the architect and never touch routes, services, or other providers.

**Reference:** `.github/copilot-instructions.md` sections: "ib_async Library", "Pattern 1–6", "IBKR-Specific Debug Patterns".

---

## Owned Files

| File | Your responsibility |
|------|-------------------|
| `app/providers/ibkr.py` | All changes |
| `app/config.py` | IBKR_* keys only — read-only otherwise |
| `scripts/diagnostics/test_ibkr_*.py` | Diagnostic scripts for live validation |

**Do not touch:** routes, services, other providers, models (unless a new model field is needed — coordinate with `@fastapi` first).

---

## IBKR Config Keys (app/config.py)

```python
IBKR_HOST: str = "127.0.0.1"
IBKR_PORT: int = 4001          # Gateway=4001, TWS paper=7497
IBKR_CLIENT_ID: int = 815      # Must be unique per connection
IBKR_MARKET_DATA_TYPE: int = 1 # 1=Live, 2=Frozen, 3=Delayed, 4=Delayed+Frozen
IBKR_CONNECT_ON_REQUEST: bool = False
IBKR_FALLBACK_ON_SUBSCRIPTION_ERROR: bool = True
IBKR_TIMEOUT_SECONDS: int = 10
IBKR_OPTIONS_TIMEOUT_SECONDS: int = 15
```

---

## Critical Patterns (never deviate)

### NaN Guard — use before every value access

```python
def _is_valid(self, val) -> bool:
    return val is not None and not (isinstance(val, float) and math.isnan(val))

def _to_decimal(self, val) -> Optional[Decimal]:
    return Decimal(str(val)) if self._is_valid(val) else None
```

IBKR returns `float('nan')` (not `None`) for unavailable fields. `-1` is also invalid for bid/ask.

### Contract Qualification — always before reqMktData

```python
qualified = await self.ib.qualifyContractsAsync(contract)
if not qualified:
    raise DataNotFoundError("Contract", symbol, details={"reason": "qualification failed"})
```

### Connection Management

```python
await self._ensure_connection()  # Always first line of every public method
```

`_ensure_connection` installs `_on_ib_error` event handler on first connect. Do not call `ib.connect()` directly.

### Subscription Errors

- Error codes 10089 / 10091: Level 1 → raise `ProviderError(PROVIDER_NOT_AVAILABLE)`.
- Level 2/3 (set via `_set_market_data_type`): graceful fallback to historical daily close.
- `IBKR_FALLBACK_ON_SUBSCRIPTION_ERROR=True` → log warning and continue with partial data.

### Options — use streaming, not snapshot

```python
ticker = self.ib.reqMktData(contract, genericTickList, snapshot=False, regulatorySnapshot=False)
await asyncio.sleep(self.options_timeout)
self.ib.cancelMktData(contract)
```

Snapshot mode returns stale Greeks. Streaming gives live Greeks during market hours.

### Async patterns

```python
# Wait for data, don't block event loop
await asyncio.sleep(seconds)    # not time.sleep()

# Blocking calls in async context
result = await asyncio.to_thread(blocking_fn, *args)
```

---

## Error Mapping

| Situation | Raise |
|-----------|-------|
| TWS/Gateway not running | `ProviderConnectionError` with host/port details |
| Contract not found / unqualifiable | `DataNotFoundError("Contract", symbol)` |
| No market data subscription (10091) | `ProviderNotAvailableError` or fallback |
| Request timeout | `ProviderTimeoutError` |
| Bad symbol / wrong params | `DataNotFoundError` |

All from `app/utils/errors.py`. Never raise raw `Exception`.

---

## Provider Interface (implement all)

```python
# Price
async def get_last_price(self, symbol: str, market_data_type: int = 1, sec_type: str = "STK", ...) -> PriceQuote
async def get_historical_prices(self, symbol: str, interval: str, period: str, ...) -> list[PriceBar]

# Company
async def get_company_profile(self, symbol: str) -> CompanyProfile
async def search_companies(self, query: str) -> list[CompanySummary]

# Options
async def get_option_chain(self, symbol: str, min_strike, max_strike, right, expiry, market_data_type, include_level2) -> list[OptionChain]
async def get_option_quote(self, symbol: str, option_id: str, market_data_type, include_level2) -> OptionQuote
```

---

## Key Internal Methods

| Method | Purpose |
|--------|---------|
| `_ensure_connection` | Lazy async connect, installs error handler |
| `_set_market_data_type(n)` | Sets IBKR market data type 1-4 |
| `_get_tickers_snapshot(contracts, timeout)` | Batch market data request |
| `_extract_greeks(ticker)` | Safe Greek extraction from ib_async Ticker |
| `_on_ib_error(reqId, errorCode, errorString, contract)` | Error event handler |
| `_handle_subscription_error(msg, contract_info)` | Returns bool: continue with fallback? |
| `_is_market_open` | Returns bool, uses `_get_trading_hours` |
| `_create_contract(symbol, sec_type, exchange, currency)` | Contract factory |
| `_map_interval(interval)` | API interval string → IBKR barSizeSetting |
| `_calculate_duration(period)` | API period string → IBKR durationStr |

---

## Verification

After changes:

```bash
# 1. Lint
uv run ruff check app/providers/ibkr.py

# 2. Unit tests (no live IBKR needed)
uv run pytest tests/ -k "ibkr" --disable-warnings

# 3. Live integration (only with running Gateway)
python scripts/diagnostics/test_ibkr_connection.py
python scripts/diagnostics/test_market_data_type.py
```

Never run live integration tests without a running TWS/Gateway and valid credentials.
```
