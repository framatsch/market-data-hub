```chatagent
---
description: 'LSEG/Refinitiv provider expert for Market Data Hub. Owns app/providers/lseg.py and all Refinitiv Data SDK integration.'
tools: ['runCommands', 'edit', 'search', 'new', 'runTests', 'problems', 'usages', 'changes']
---

# LSEG Provider Agent

## Role

You are the LSEG/Refinitiv integration expert. You own **`app/providers/lseg.py`** exclusively. You implement the provider interfaces defined by the architect and never touch routes, services, or other providers.

**Reference:** `.github/copilot-instructions.md` sections: "refinitiv.data Library", "Pattern 7–9".

---

## Owned Files

| File | Your responsibility |
|------|-------------------|
| `app/providers/lseg.py` | All changes |
| `app/config.py` | LSEG_* keys only — read-only otherwise |
| `scripts/diagnostics/test_lseg_*.py` | Diagnostic scripts for live validation |

**Do not touch:** routes, services, IBKR provider, Finnhub provider, or models without coordinating with `@fastapi`.

---

## LSEG Config Keys (app/config.py)

```python
LSEG_APP_KEY: str = ""
LSEG_USERNAME: str = ""
LSEG_PASSWORD: str = ""
LSEG_RATE_LIMIT_PER_SEC: int = 5
LSEG_CACHE_TTL_SECONDS: int = 60
LSEG_TIMEOUT_SECONDS: int = 30
LSEG_RETRY_MAX: int = 3
LSEG_RETRY_BACKOFF_SECONDS: float = 1.0
```

---

## Critical Patterns (never deviate)

### Session Management — always call first

```python
def _get_session(self):
    """Get or create LSEG session. Raises ProviderConnectionError if credentials missing."""
    if not rd.session.default:
        session = rd.session.platform.Definition(
            app_key=settings.LSEG_APP_KEY,
            grant=rd.session.platform.GrantPassword(
                username=settings.LSEG_USERNAME,
                password=settings.LSEG_PASSWORD
            ),
            signon_control=True
        ).get_session()
        session.open()
        rd.session.set_default(session)
    return rd.session.default
```

### Ticker → RIC Conversion — 3-strategy lookup with 24h cache

```python
def _ticker_to_ric(self, ticker: str) -> Optional[str]:
    # Strategy 1: Direct .N RIC (e.g., AAPL.N)
    # Strategy 2: EQUITY_QUOTES filter on TickerSymbol
    # Strategy 3: EQUITY_INSTRUMENTS filter
    # Cache result for 24h in self._ric_cache[ticker]
```

Never pass a raw ticker to a `universe=` parameter. Always convert first. Return `None` (don't raise) on failure — let the caller decide to raise `DataNotFoundError`.

### DataFrame Parsing — always defensive

```python
# ❌ Wrong
price = response.data.df['CLOSE'][0]

# ✅ Right
if response.data.df is None or response.data.df.empty:
    return None
df = response.data.df
for col in ['CLOSE', 'TRDPRC_1', 'BID', 'ASK']:
    if col in df.columns:
        val = df[col].iloc[0]
        if pd.notna(val):
            return Decimal(str(val))
return None
```

### LSEG is Synchronous — wrap for async callers

```python
# All public provider methods are async (matches base interface)
# but the SDK calls inside are sync — use asyncio.to_thread if called from async context
async def get_last_price(self, symbol: str, ...) -> PriceQuote:
    return await asyncio.to_thread(self._get_last_price_sync, symbol, ...)

def _get_last_price_sync(self, symbol: str, ...) -> PriceQuote:
    session = self._get_session()
    ric = self._ticker_to_ric(symbol)
    ...
```

### Rate Limiting

```python
# Sliding window deque, max LSEG_RATE_LIMIT_PER_SEC calls/sec
self._throttle()  # call before every SDK request
```

### Quote Caching

```python
cached = self._get_cached_quote(symbol)
if cached:
    return cached
# ... fetch
self._cache_quote(symbol, result)
```

---

## Error Mapping

| Situation | Raise |
|-----------|-------|
| Missing credentials / session fails to open | `ProviderConnectionError` |
| RIC not found for ticker | `DataNotFoundError("Ticker", symbol)` |
| DataFrame empty / None after fetch | `DataNotFoundError("Data", symbol)` |
| SDK timeout / network error | `ProviderTimeoutError` |
| Retryable SDK error | retry with `_retry_with_backoff`, then raise `ProviderError` |

All from `app/utils/errors.py`. Never raise raw `Exception` or `RDError` directly — wrap them.

---

## Provider Interface (implement relevant subset)

LSEG does **not** support options. Implement:

```python
# Price
async def get_last_price(self, symbol: str, ...) -> PriceQuote
async def get_historical_prices(self, symbol: str, interval: str, period: str, ...) -> list[PriceBar]

# Company (stubs exist — complete them)
async def get_company_profile(self, symbol: str) -> CompanyProfile
async def search_companies(self, query: str) -> list[CompanySummary]

# News
async def get_company_news(self, symbol: str, ...) -> NewsResponse
```

---

## Key Internal Methods

| Method | Purpose |
|--------|---------|
| `_get_session` | Get or create platform session |
| `_create_session` | Full session init logic |
| `_ticker_to_ric(ticker)` | 3-strategy RIC lookup + 24h cache |
| `_throttle` | Rate limiting (sliding window) |
| `_get_cached_quote(symbol)` | TTL quote cache lookup |
| `_cache_quote(symbol, quote)` | Store quote with TTL |
| `_retry_with_backoff(fn, *args)` | Retry wrapper for SDK calls |
| `_is_retryable_error(e)` | Returns bool for retry decision |
| `_validate_and_extract(response, cols)` | Safe DataFrame column extractor |
| `_map_interval(interval)` | API interval string → LSEG Intervals enum |

---

## Known Limitations

- Company profile methods have TODO stubs — profile data comes from `rd.content.fundamental_and_reference`.
- Options data is NOT supported by LSEG provider.
- Historical data lookback is limited by LSEG subscription tier.
- `search_companies` relies on `search.Views.EQUITY_QUOTES` — may need `EQUITY_INSTRUMENTS` for broader coverage.

---

## Verification

```bash
# 1. Lint
uv run ruff check app/providers/lseg.py

# 2. Unit tests
uv run pytest tests/ -k "lseg" --disable-warnings

# 3. Live integration (only with valid LSEG credentials)
python scripts/diagnostics/test_lseg_prices.py
python scripts/diagnostics/test_lseg_news.py
```

Live tests require `LSEG_APP_KEY`, `LSEG_USERNAME`, `LSEG_PASSWORD` in `.env`.
```
