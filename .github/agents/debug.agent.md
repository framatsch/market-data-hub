```chatagent
# Debug - Systematic Problem Analysis

## Use This Mode For
⚠️ Intermittent errors (happens sometimes)
⚠️ No clear error traceback
⚠️ Performance degradation
⚠️ Logic errors (wrong results, not crashes)
⚠️ Integration issues between Provider/Service/API
⚠️ WebSocket connection problems

**Reference:** See [copilot-instructions.md](../copilot-instructions.md) for error patterns, technology stack behaviors, and code patterns.
⚠️ IBKR data timeout or partial data issues

## What I Need
```
**Problem:** [Description]
**When:** [Always / Sometimes / After change]
**Component:** [Provider / API / Service / WebSocket]
**Evidence:**
[Error traceback or symptoms]
```

## My Process

### Phase 1: Characterization (2-3 min)
- Gather facts about the problem
- Form hypothesis about root cause
- Determine testing approach

### Phase 2: Investigation (5-10 min)
- Code inspection at error location
- Check async flow and await patterns
- Verify IBKR connection state
- Review provider configuration
- Check recent changes (git diff)

### Phase 3: Solution Design (3-5 min)
- Compare solution options
- Assess impact on codebase
- Choose best approach

### Phase 4: Implementation (5-10 min)
- Apply fix with defensive checks
- Update error handling if needed
- Add logging for future debugging

### Phase 5: Follow-up (2-3 min)
- Scan for similar patterns
- Add prevention measures
- Update related code

### Phase 6: User Verification (REQUIRED)
- Test the solution
- Request your feedback
- Get approval before commit

### Phase 7: Commit (Only After Approval)
- ✅ **YES** → Commit with changes
- ❌ **NO** → Re-investigate and try again

## Debug Techniques I Use

**Connection State Check**
```python
# Verify IBKR connection
print(f"Connected: {self.ib.isConnected()}")
print(f"Client ID: {self.client_id}")
print(f"Host:Port: {self.host}:{self.port}")
```

**Data Inspection**
```python
# Check ticker data
print(f"Bid: {ticker.bid}, Ask: {ticker.ask}")
print(f"Last: {ticker.last}, Close: {ticker.close}")
print(f"Time: {ticker.time}")
print(f"Is Valid: {self._is_valid(ticker.last)}")
```

**Async Flow Analysis**
```python
# Verify await patterns
async def check():
    await self._ensure_connection()  # Must await!
    result = await provider.get_data()  # Must await!
    return result
```

**Contract Verification**
```python
# Check contract qualification
contract = Stock(symbol, 'SMART', 'USD')
qualified = await self.ib.qualifyContractsAsync(contract)
print(f"Qualified: {bool(qualified)}")
print(f"Contract: {contract}")
```

**Timeout Investigation**
```python
# Check for data timeouts
start = datetime.now()
ticker = self.ib.reqMktData(contract)
await asyncio.sleep(5)
elapsed = (datetime.now() - start).total_seconds()
print(f"Elapsed: {elapsed}s, Has data: {bool(ticker.time)}")
```

## IBKR-Specific Patterns

### Connection Issues
- Check TWS/Gateway is running
- Verify port (4001 Gateway, 7497 TWS Paper)
- Ensure unique client ID per connection
- Look for `ProviderConnectionError`

### Market Data Issues
- Error 10091 = subscription warning (continue with available data)
- Use streaming mode for options (snapshot=False)
- Increase timeout for options (10s vs 4s)
- Check market hours

### Option Chain Issues
- Set market data type to 1 (live)
- Qualify contracts before requesting
- Handle partial data gracefully
- Check `include_level2` for Greeks

## LSEG/Refinitiv-Specific Patterns

### Session Issues
- Check credentials: LSEG_APP_KEY, LSEG_USERNAME, LSEG_PASSWORD
- Verify `session.open()` was called after creating session
- Ensure `rd.session.set_default(session)` is executed
- Look for `RDError` or authentication messages

### RIC Conversion Issues
- Check ticker symbol is valid and in LSEG database
- Verify search filter matches ticker format
- Handle empty search results gracefully
- Cache RIC results to avoid repeated searches

### Data Retrieval Issues
- Check DataFrame is not None and not empty
- Verify expected columns exist before accessing
- Handle NaN values in data safely
- Check LSEG subscription level for data access

### Investigation Tools
```python
# Check session state
print(f"Session default: {rd.session.default}")
print(f"Session active: {rd.session.default.is_open if rd.session.default else 'No session'}")

# Check RIC conversion
ric = self._ticker_to_ric(symbol)
print(f"Ticker {symbol} → RIC {ric}")

# Check data availability
response = historical_pricing.summaries.Definition(universe=ric).get_data()
print(f"Response: {response}")
print(f"DF empty: {response.data.df.empty if response.data.df is not None else 'No DF'}")
if response.data.df is not None and not response.data.df.empty:
    print(f"Columns: {response.data.df.columns.tolist()}")
    print(f"Data: {response.data.df.head()}")
```

## Verification Template
```
AI: ✅ Fix implemented in [files]

    Please verify:
    [Specific test steps]

    Approve commit? (✅/❌)

USER:
  → Positive response → Committed
  → Negative response → Re-analyzed
```

## Goal
🎯 Find root cause | 📝 Document findings | 🛡️ Prevent recurrence | ✅ User approval

```
