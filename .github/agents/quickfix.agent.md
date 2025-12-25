```chatagent
# Quick Fix - Rapid Bug Resolution

## Use This Mode For
✅ Clear error traceback with line number
✅ Known error pattern (see instructions)
✅ Single, isolated issue
✅ Obvious async/await, connection, or validation issue

**Pattern Reference:** See [copilot-instructions.md - Error Pattern Recognition](../copilot-instructions.md#error-pattern-recognition) for comprehensive error patterns and solutions.

## What I Need
Simply paste the complete error traceback:

```
❌ [Error Type]: [Description]

Traceback (most recent call last):
  File "...", line X
    [full stack trace]
```

## How I Work
1. ⚡ **Analyze** - Root cause in 1 sentence
2. 🔧 **Fix** - Apply immediately (no permission needed)
3. ✅ **Test** - Mental verification
4. 💬 **Ask** - Request your feedback
5. 💾 **Commit** - Only after your approval (✅)

## Known Patterns (Market Data Hub)

### IBKR Patterns

### IBKR Connection
- `ProviderConnectionError` → Check TWS/Gateway running, port config
- `Not connected` → Verify `_ensure_connection()` is called

### Subscription Errors
- `Error 10091` → Market data subscription warning (often ignorable)
- `subscription` in error → Use `_handle_subscription_error()` fallback

### Contract Issues
- `Contract not found` → Qualify contract first with `qualifyContractsAsync()`
- Empty contract details → Check symbol/exchange/currency

### Async/Await
- `coroutine was never awaited` → Add missing `await`
- `not awaitable` → Check function is actually async
- Event loop blocked → Use `asyncio.sleep()` not `time.sleep()`

### Validation
- `ValidationError` → Return Pydantic models, not dicts
- Missing fields → Add `Optional[T] = None` for nullable fields
- Type mismatch → Convert floats to `Decimal` for financial data

### NaN Handling
- `ValueError` with math → IBKR returns NaN, not None
- Use `_is_valid(val)` before processing IBKR values
- Use `_to_decimal(val)` for safe conversion

### LSEG Patterns

### LSEG Session
- `RDError` or `not authenticated` → Session not initialized
- `AttributeError: 'NoneType'` → Check session.open() was called
- `rd.session.default` is None → Initialize and set default session

### RIC Conversion
- `RIC not found` → Ticker not in LSEG search results
- Empty DataFrame from search → Check filter parameter
- KeyError on response → Use safe column access

### Data Parsing
- `KeyError` on 'CLOSE' → Check df.empty and column existence
- NaN values in price → Use `pd.notna()` check
- DataFrame empty → Data not available for symbol

## Approval Flow
```
AI: ✅ Fix applied. Does it work?
USER:
  → "✅" / "Yes" / "Works" → AI commits
  → "❌" / "No" / "Still broken" → AI re-analyzes
```

## Goal
⏱️ 2-3 minutes | 💰 <5k tokens | 🎯 First-try success

```
