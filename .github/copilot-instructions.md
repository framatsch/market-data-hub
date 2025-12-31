# 🤖 Copilot Instructions - Market Data Hub

**Version:** 2.0 (with LSEG/Refinitiv)
**Last Updated:** 2025-12-25
**Project:** Market Data Hub (FastAPI + IBKR + LSEG/Refinitiv)

## Overview

You are an expert AI assistant for the Market Data Hub project. This document defines your behavior, decision-making process, and best practices for this specific codebase.

**Project Context:**
- FastAPI-based REST/WebSocket API for market data aggregation
- Dual provider pattern: IBKR (primary) + LSEG/Refinitiv (secondary)
- IBKR: Async Python with `ib_async` library for Interactive Brokers
- LSEG: Synchronous `refinitiv.data` SDK with session-based authentication
- Options chains, price quotes, company data, historical data endpoints
- Kubernetes-ready with Docker deployment

## Core Principles

### 1. Efficiency First
- Minimize token usage through focused analysis
- Read only affected file sections (use line numbers from tracebacks)
- Apply fixes immediately without permission for clear issues
- Use multi-operation tools when multiple changes needed

### 2. Type Safety
- Always use Pydantic models for API request/response validation
- Explicit `Optional[]` typing for nullable fields
- Use `Decimal` for financial values (not float)
- Proper async/await patterns throughout

### 3. Quality Assurance
- Verify fixes address root cause (not just symptoms)
- Check for similar patterns in related files
- Mental verification for simple fixes
- Quick Python tests for complex logic
- **Every commit must pass linting**: Run `ruff check app/` before changes
- Code in `scripts/diagnostics/` and `tests` is excluded from CI linting (development-only)
- Never commit without user approval

### 4. Clear Communication
- Explain WHY before WHAT (1 sentence max for simple issues)
- Use structured formatting for complex problems
- Ask clarifying questions only when truly needed
- Provide actionable next steps

---

## Error Pattern Recognition

### Pattern 1: IBKR Connection Errors
**Symptom:** `ProviderConnectionError: Could not connect to IBKR`
**Root Cause:** TWS/Gateway not running or wrong port/host
**File Locations:** `app/providers/ibkr.py` - `_ensure_connection()`

**Solution:**
```python
# ❌ Wrong - No proper error context
raise Exception("Connection failed")

# ✅ Right - Structured error with details
raise ProviderConnectionError(
    f"Could not connect to IBKR at {self.host}:{self.port}",
    details={"host": self.host, "port": self.port, "client_id": self.client_id}
)
```

**Troubleshooting:**
- Check TWS/Gateway is running
- Verify port (4001 for Gateway, 7497 for TWS paper)
- Check client ID not already in use
- Enable API connections in TWS settings

---

### Pattern 2: Market Data Subscription Errors (Error 10091)
**Symptom:** `Error 10091: No market data subscription` or similar warnings
**Root Cause:** Missing market data subscription for requested instrument
**File Locations:** `app/providers/ibkr.py` - `_get_tickers_snapshot()`, `_handle_subscription_error()`

**Solution:**
```python
# ❌ Wrong - Raise immediately on subscription error
if "subscription" in error_msg:
    raise ProviderError("No subscription")

# ✅ Right - Graceful degradation with fallback
def _handle_subscription_error(self, error_msg: str, contract_info: str = "") -> bool:
    if "subscription" in error_msg.lower() or "10091" in error_msg:
        self._subscription_errors.append({
            "contract": contract_info,
            "error": error_msg,
            "timestamp": datetime.now()
        })
        logger.warning(f"Subscription error: {error_msg}. Contract: {contract_info}")
        return self.fallback_on_subscription_error  # Continue with available data
    return False
```

**Configuration:**
- `IBKR_FALLBACK_ON_SUBSCRIPTION_ERROR=True` - Continue with partial data
- `IBKR_MARKET_DATA_TYPE=1` - Use live data (best for options)

---

### Pattern 3: Contract Qualification Failures
**Symptom:** `Contract not found` or empty contract details
**Root Cause:** Invalid symbol, exchange, or contract parameters
**File Locations:** `app/providers/ibkr.py` - `get_option_chain()`, `get_last_price()`

**Solution:**
```python
# ❌ Wrong - Assume contract is valid
ticker = self.ib.reqMktData(contract)

# ✅ Right - Qualify contract first
qualified = await self.ib.qualifyContractsAsync(contract)
if not qualified:
    raise DataNotFoundError("Contract", f"{symbol}",
        details={"reason": "Contract could not be qualified"})
```

**Prevention:**
- Always qualify contracts before requesting data
- Use correct exchange (SMART for US stocks)
- Verify currency matches (USD for US markets)

---

### Pattern 4: Async/Await Misuse
**Symptom:** `RuntimeWarning: coroutine was never awaited` or `TypeError: object is not awaitable`
**Root Cause:** Missing await or calling sync from async context
**File Locations:** All async handlers in `app/api/routes_*.py`, `app/providers/*.py`

**Solution:**
```python
# ❌ Wrong - Missing await
async def get_prices():
    return provider.get_last_price(symbol)  # Coroutine, not result!

# ✅ Right - Proper await
async def get_prices():
    return await provider.get_last_price(symbol)

# ❌ Wrong - Blocking call in async context
def sync_call():
    time.sleep(5)  # Blocks event loop!

# ✅ Right - Async sleep
await asyncio.sleep(5)
```

**Prevention:**
- Always `await` coroutines
- Use `asyncio.sleep()` not `time.sleep()`
- Use `asyncio.to_thread()` for blocking I/O

---

### Pattern 5: Pydantic Validation Errors
**Symptom:** `ValidationError: X validation errors for Model`
**Root Cause:** Missing required fields or wrong types in API responses
**File Locations:** `app/models/*.py`, `app/api/routes_*.py`

**Solution:**
```python
# ❌ Wrong - Direct dict return without validation
return {"price": price, "symbol": symbol}

# ✅ Right - Pydantic model validation
return PriceQuote(
    symbol=symbol,
    last_price=Decimal(str(price)) if price else None,
    timestamp=datetime.now(timezone.utc)
)
```

**Prevention:**
- Always return Pydantic models from endpoints
- Use `Optional[T]` for nullable fields
- Convert floats to Decimal for financial data

---

### Pattern 6: NaN/None Handling in Financial Data
**Symptom:** `ValueError` or incorrect calculations with NaN values
**Root Cause:** IBKR returns NaN for unavailable data, not None
**File Locations:** `app/providers/ibkr.py` - `_to_decimal()`, `_is_valid()`

**Solution:**
```python
# ❌ Wrong - Only check for None
if value is not None:
    return Decimal(str(value))

# ✅ Right - Check for NaN as well
def _is_valid(self, val) -> bool:
    return val is not None and not (isinstance(val, float) and math.isnan(val))

def _to_decimal(self, val) -> Optional[Decimal]:
    if self._is_valid(val):
        return Decimal(str(val))
    return None
```

**Prevention:**
- Always use `_is_valid()` helper before processing IBKR values
- Use `_to_decimal()` for safe conversion
- Handle -1 as invalid (IBKR uses -1 for unavailable bid/ask)

---

### Pattern 7: LSEG/Refinitiv Session Errors
**Symptom:** `RDError` or session not authenticated
**Root Cause:** Session not initialized or credentials invalid
**File Locations:** `app/providers/lseg.py` - `_get_session()`, `_ensure_session()`

**Solution:**
```python
# ❌ Wrong - No session management
response = rd.discover.chain_expansion(universe=symbol)

# ✅ Right - Initialize and manage session
def _get_session(self):
    """Get or create LSEG session with proper authentication."""
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

**Configuration:**
- `LSEG_APP_KEY` - Application API key from LSEG console
- `LSEG_USERNAME` - LSEG platform username
- `LSEG_PASSWORD` - LSEG platform password

---

### Pattern 8: Ticker to RIC Conversion Failures
**Symptom:** `RIC not found` or empty search results
**Root Cause:** Invalid ticker symbol or search filter mismatch
**File Locations:** `app/providers/lseg.py` - `_ticker_to_ric()`, search handlers

**Solution:**
```python
# ❌ Wrong - Direct RIC lookup without search
ric = ticker  # Assumes ticker is RIC (fails for AAPL, MSFT, etc.)

# ✅ Right - Convert ticker to RIC via search
def _ticker_to_ric(self, ticker: str) -> Optional[str]:
    """Convert stock ticker symbol to LSEG RIC code."""
    try:
        response = search.Definition(
            view=search.Views.EQUITY_QUOTES,
            query=ticker,
            filter=f"TickerSymbol eq '{ticker}'",
            select="RIC, DisplayName, TickerSymbol",
            top=1
        ).get_data()

        if not response.data.df.empty:
            return response.data.df.iloc[0]['RIC']
        return None
    except Exception as e:
        logger.warning(f"RIC lookup failed for {ticker}: {e}")
        return None
```

**Prevention:**
- Always use search to convert ticker → RIC
- Validate response before accessing DataFrame
- Cache RIC results for frequently used tickers
- Handle search timeouts gracefully

---

### Pattern 9: Refinitiv Data Parsing Errors
**Symptom:** KeyError or AttributeError on DataFrame columns
**Root Cause:** Unexpected response structure or missing columns
**File Locations:** `app/providers/lseg.py` - data parsing methods

**Solution:**
```python
# ❌ Wrong - Assume columns exist
price = response.data.df['CLOSE'][0]

# ✅ Right - Check columns and handle missing data
def _extract_price(self, response, ticker: str) -> Optional[Decimal]:
    """Safely extract price from LSEG response."""
    if not response or not response.data.df is not None or response.data.df.empty:
        logger.warning(f"No data for {ticker}")
        return None

    df = response.data.df
    # Try multiple possible column names
    for col in ['CLOSE', 'TRDPRC_1', 'BID', 'ASK']:
        if col in df.columns:
            value = df[col].iloc[0]
            if pd.notna(value):
                return Decimal(str(value))
    return None
```

**Prevention:**
- Check response.data.df is not None
- Verify DataFrame is not empty
- Use safe column access with `.get()` or check columns first
- Handle NaN values with `pd.notna()`
- Log unexpected responses for debugging

---

## Technology Stack - Specific Behaviors

### FastAPI Framework
- **Entry point:** `app/main.py`
- **Routing:** Separate router files in `app/api/routes_*.py`
- **Error handling:** Custom `AppError` exceptions with HTTP status mapping
- **Dependency injection:** Use `app/dependencies.py` for provider instances
- **Common patterns:**
  ```python
  @router.get("/endpoint", response_model=ResponseModel)
  async def endpoint_handler(
      symbol: str,
      provider: BasePriceProvider = Depends(get_price_provider)
  ) -> ResponseModel:
      return await provider.get_data(symbol)
  ```

### ib_async Library
- **Connection:** Use `ib.connectAsync()` for non-blocking connect
- **Market data:** `ib.reqMktData()` returns ticker, wait for data
- **Historical data:** `ib.reqHistoricalDataAsync()` returns bars
- **Options:** Qualify contracts before requesting data
- **Disconnect:** Cancel subscriptions before disconnect
- **Common patterns:**
  ```python
  await self._ensure_connection()
  contract = Stock(symbol, 'SMART', 'USD')
  qualified = await self.ib.qualifyContractsAsync(contract)
  ticker = self.ib.reqMktData(contract, '', snapshot=True, regulatorySnapshot=False)
  await asyncio.sleep(2)  # Wait for data
  self.ib.cancelMktData(contract)
  ```

### refinitiv.data Library (LSEG)
- **Session Management:** Synchronous platform session with signon_control
- **Authentication:** GrantPassword with username/password credentials
- **Search:** `search.Definition()` to find instruments and convert ticker → RIC
- **Data Retrieval:** Use appropriate view (EQUITY_QUOTES, EQUITY_FUNDAMENTALS, etc.)
- **Response Parsing:** Returns pandas DataFrame in response.data.df
- **Common patterns:**
  ```python
  # Initialize session
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

  # Search and convert ticker to RIC
  response = search.Definition(
      view=search.Views.EQUITY_QUOTES,
      query=symbol,
      filter=f"TickerSymbol eq '{symbol}'",
      select="RIC, DisplayName, TickerSymbol",
      top=1
  ).get_data()

  if not response.data.df.empty:
      ric = response.data.df.iloc[0]['RIC']

  # Get historical data
  response = historical_pricing.summaries.Definition(
      universe=ric,
      interval=historical_pricing.Intervals.DAILY,
      count=1
  ).get_data()

  if response.data.df is not None and not response.data.df.empty:
      price = response.data.df['CLOSE'].iloc[0]
  ```

### Pydantic Models
- **Location:** `app/models/` directory
- **Base patterns:** Inherit from `BaseModel`
- **Financial data:** Use `Decimal` type, not `float`
- **Timestamps:** Use `datetime` with timezone awareness
- **Optional fields:** Explicit `Optional[T] = None`
- **Common patterns:**
  ```python
  class PriceQuote(BaseModel):
      symbol: str
      last_price: Optional[Decimal] = None
      bid: Optional[Decimal] = None
      ask: Optional[Decimal] = None
      timestamp: datetime
  ```

### Error Handling
- **Base class:** `AppError` with code, message, details
- **HTTP mapping:** In `app/main.py` exception handler
- **Error codes:** `DATA_NOT_FOUND` (404), `INVALID_PROVIDER` (400), `PROVIDER_TIMEOUT` (503)
- **Common patterns:**
  ```python
  class DataNotFoundError(AppError):
      def __init__(self, entity: str, identifier: str, details: Optional[Dict] = None):
          super().__init__(f"{entity} '{identifier}' not found", "DATA_NOT_FOUND", details)
  ```

---

## Code Patterns - Implementation Templates

Standardized code patterns for common development tasks in Market Data Hub.

### FastAPI Route Pattern
```python
@router.get("/endpoint/{symbol}", response_model=ResponseModel)
async def get_data(
    symbol: str,
    provider: BaseProvider = Depends(get_provider)
) -> ResponseModel:
    return await provider.get_data(symbol)
```

### Pydantic Model Pattern
```python
class NewModel(BaseModel):
    symbol: str
    value: Optional[Decimal] = None
    timestamp: datetime
```

### IBKR Provider Method Pattern
```python
async def new_method(self, symbol: str) -> NewModel:
    await self._ensure_connection()
    contract = Stock(symbol, 'SMART', 'USD')
    qualified = await self.ib.qualifyContractsAsync(contract)
    if not qualified:
        raise DataNotFoundError("Contract", symbol)
    # ... implementation
    return NewModel(...)
```

### LSEG Provider Method Pattern
```python
def new_method(self, symbol: str) -> NewModel:
    """LSEG is synchronous, no async needed."""
    session = self._get_session()  # Get default session

    # Convert ticker to RIC
    ric = self._ticker_to_ric(symbol)
    if not ric:
        raise DataNotFoundError("Ticker", symbol)

    # Fetch data
    response = historical_pricing.summaries.Definition(
        universe=ric,
        interval=historical_pricing.Intervals.DAILY,
        count=1
    ).get_data()

    if response.data.df is None or response.data.df.empty:
        raise DataNotFoundError("Data", symbol)

    price = Decimal(str(response.data.df['CLOSE'].iloc[0]))
    return NewModel(symbol=symbol, value=price, timestamp=datetime.now(timezone.utc))
```

### Error Handling Pattern
```python
try:
    result = await provider.get_data(symbol)
except ProviderConnectionError:
    raise HTTPException(status_code=503, detail="Provider unavailable")
except DataNotFoundError as e:
    raise HTTPException(status_code=404, detail=str(e))
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    raise HTTPException(status_code=500, detail="Internal server error")
```

---

## File Structure Knowledge

```
market-data-hub/
├── app/
│   ├── main.py                  # FastAPI app, exception handlers, routers
│   ├── config.py                # Settings from environment variables
│   ├── dependencies.py          # Dependency injection for providers
│   ├── api/
│   │   ├── routes_meta.py       # Health check, status endpoints
│   │   ├── routes_prices.py     # Price quotes, historical data
│   │   ├── routes_companies.py  # Company profiles, search
│   │   ├── routes_options.py    # Option chains, quotes
│   │   └── routes_ws.py         # WebSocket price streaming
│   ├── models/
│   │   ├── common.py            # Shared models
│   │   ├── price.py             # PriceBar, PriceQuote
│   │   ├── company.py           # CompanyProfile, CompanySummary
│   │   └── options.py           # OptionChain, OptionQuote
│   ├── providers/
│   │   ├── base.py              # Abstract provider interfaces
│   │   ├── ibkr.py              # IBKR implementation (ib_async)
│   │   ├── lseg.py              # LSEG implementation (REST API)
│   │   └── registry.py          # Provider registration/lookup
│   ├── services/
│   │   ├── price_service.py     # Price data orchestration
│   │   ├── company_service.py   # Company data orchestration
│   │   └── options_service.py   # Options data orchestration
│   └── utils/
│       ├── errors.py            # Custom exception classes
│       └── logging.py           # Logging configuration
├── tests/
│   └── integration/
│       ├── test_ibkr.py         # IBKR provider integration tests
│       └── test_ibkr_http.py    # HTTP API integration tests
├── k8s/
│   ├── deployment.yaml          # Kubernetes deployment
│   └── service.yaml             # Kubernetes service
├── specs/                       # Feature specifications
├── .github/
│   ├── copilot-instructions.md  # This file
│   ├── COPILOT_GUIDE.md         # Quick reference guide
│   └── agents/                  # Workflow agents
├── Dockerfile                   # Container build
├── pyproject.toml               # Python project config
└── README.md                    # Project documentation
```

**Data Flow:**
```
HTTP Request → FastAPI Router → Service Layer → Provider (IBKR/LSEG)
                                                      ↓
HTTP Response ← Pydantic Model ← Service Layer ← External API
```

---

## Workflow Modes

This project uses specialized workflow modes for different types of work:

1. **Quick Fix Mode** - Fast fixes for known error patterns
2. **Debug Mode** - Systematic debugging for complex issues
3. **Plan Feature Mode** - Interactive feature specification generation
4. **Implement Feature Mode** - Automated feature implementation from specs

### Mode Selection Decision Tree

```
Is this a new feature request?
├─ Yes → Plan Feature Mode → Generate spec → Implement Feature Mode
└─ No → Is it a bug/error?
    ├─ Yes → Clear error traceback with line number?
    │  ├─ Yes → Known pattern? (see Patterns above)
    │  │  ├─ Yes → Quick Fix Mode
    │  │  └─ No → Is fix obvious? (connection, timeout, validation)
    │  │     ├─ Yes → Quick Fix Mode
    │  │     └─ No → Debug Mode
    │  └─ No → Debug Mode
    └─ No → Debug Mode

Problem is intermittent/data-dependent?
├─ Yes → Debug Mode
└─ No → Quick Fix Mode

Multiple components affected (Provider + API + Service)?
├─ Yes → Debug Mode
└─ No → Quick Fix Mode
```

---

## Quick Fix Mode Workflow

**Use this mode when:**
- ✅ Clear error traceback with line number
- ✅ Known error pattern (see Pattern Recognition section)
- ✅ Single, isolated issue
- ✅ Obvious async/await, type, or connection issue

### Execution Steps

1. **Error Analysis** (Auto-execute)
   - Identify error type (ConnectionError, ValidationError, etc.)
   - Locate exact file and line number from traceback
   - Determine root cause in 1-2 sentences
   - Check for similar patterns in related files

2. **Solution Implementation** (Direct action)
   - Show specific code fix with proper context
   - Explain WHY (1 sentence) before showing WHAT
   - Apply fix immediately - don't ask permission
   - Use `multi_replace_string_in_file` for multiple fixes

3. **Verification** (Quick check)
   - Verify fix addresses root cause
   - Check for side effects in related code
   - Ensure proper error handling
   - Run `ruff check app/ tests/` to verify no linting errors

4. **Commit** (Auto-execute after user approval)
   - Run linter check before commit
   - Commit with clear message: `🔧 Fix [specific issue] in [component]`

### Quick Fix Response Format
```markdown
**Root Cause:** [1 sentence explaining WHY]

**Fix:** [Specific change needed]

[Apply fix with code]

✅ Fixed: [Brief verification]
```

---

## Debug Mode Workflow

**Use this mode when:**
- ⚠️ Error is intermittent or data-dependent
- ⚠️ Multiple error types occurring simultaneously
- ⚠️ Root cause unclear from initial traceback
- ⚠️ Performance issues without clear errors
- ⚠️ WebSocket connection issues
- ⚠️ Integration issues between Provider/Service/API

### 7-Phase Systematic Workflow

#### Phase 1: Problem Characterization (2-3 minutes)
- Gather facts: error type, frequency, impact
- Form hypothesis about root cause
- Determine test approach

#### Phase 2: Investigation (5-10 minutes)
- Code inspection at error location
- Check async flow and await patterns
- Verify provider connection state
- Review recent changes (git diff)

#### Phase 3: Solution Design (3-5 minutes)
- Compare solution options
- Assess impact on codebase
- Choose best approach

#### Phase 4: Implementation (5-10 minutes)
- Apply fix with defensive checks
- Update error handling if needed
- Add logging for future debugging
- Run `ruff check app/ tests/` to verify linting

#### Phase 5: Follow-up (2-3 minutes)
- Scan for similar patterns
- Add prevention measures
- Update related code

#### Phase 6: User Verification (REQUIRED)
- Test the solution
- Request user feedback
- Get approval before commit

#### Phase 7: Commit (Only After Approval)
- ✅ YES → Run linter, then commit with changes
- ❌ NO → Re-investigate and try again

---

## IBKR-Specific Debug Patterns

### Pattern: Connection State Issues
**Symptoms:**
- Intermittent connection failures
- "Not connected" errors after successful connection
- Multiple client ID conflicts

**Investigation:**
```python
# Check connection state
print(f"Connected: {self.ib.isConnected()}")
print(f"Client ID: {self.client_id}")

# Verify no other connections with same client ID
# Each client ID can only have one connection
```

**Common Fixes:**
- Use unique client IDs
- Implement connection pooling
- Add reconnection logic with backoff

### Pattern: Market Data Timeout
**Symptoms:**
- Empty ticker data after reqMktData
- Timeout waiting for snapshot
- Partial data received

**Investigation:**
```python
# Check what data is available
ticker = self.ib.reqMktData(contract)
await asyncio.sleep(5)  # Longer wait
print(f"Bid: {ticker.bid}, Ask: {ticker.ask}, Last: {ticker.last}")
print(f"Time: {ticker.time}")
```

**Common Fixes:**
- Increase timeout for options (10s vs 4s)
- Use streaming mode for options
- Check market hours
- Verify data subscription level

### Pattern: Option Chain Issues
**Symptoms:**
- Empty option chain returned
- Missing strikes or expirations
- Greeks not available

**Investigation:**
```python
# Verify contract details
print(f"Contract: {contract}")
print(f"Expiry: {contract.lastTradeDateOrContractMonth}")
print(f"Right: {contract.right}")
print(f"Strike: {contract.strike}")
```

**Common Fixes:**
- Set market data type to 1 (live)
- Use include_level2=True for Greeks
- Qualify contracts before requesting data
- Handle subscription limitations gracefully

---

## Commit Message Standards

**Format:**
```
[emoji] [Category]: [Specific Issue]

[Brief explanation of fix]
[Impact on API/Provider if relevant]
```

**Categories & Emojis:**
- `🔧 Fix:` Bug fixes
- `✨ Add:` New features
- `📚 Docs:` Documentation
- `🔄 Refactor:` Code reorganization
- `⚡ Perf:` Performance improvements
- `🐛 Debug:` Debugging changes
- `🔌 Provider:` Provider-specific changes
- `🌐 API:` API endpoint changes

**Examples:**
```
🔧 Fix: Handle subscription errors gracefully in IBKR provider
🔌 Provider: Add streaming mode for option data requests
🌐 API: Add include_level2 parameter to option chain endpoint
```

---

## User Approval Workflow

**NEVER commit without explicit user approval:**

1. **After fix implementation:**
   ```
   ✅ Fix applied in [files]

   Please verify:
   [Specific test steps]

   Approve commit? (✅/❌)
   ```

2. **User response:**
   - `✅` → Apply commit immediately
   - `❌` or problem description → Re-analyze and fix again

3. **Never assume** the fix works without feedback

---

## Configuration Reference

### Environment Variables (app/config.py)
```python
# General
APP_NAME = "Market Data Hub"
APP_ENV = "dev" | "test" | "prod"
LOG_LEVEL = "INFO"

# Provider Defaults
DEFAULT_PRICE_PROVIDER = "ibkr"
DEFAULT_COMPANY_PROVIDER = "lseg"
DEFAULT_OPTIONS_PROVIDER = "ibkr"

# IBKR Provider
IBKR_HOST = "127.0.0.1"
IBKR_PORT = 4001              # Gateway: 4001, TWS Paper: 7497
IBKR_CLIENT_ID = 815          # Must be unique per connection
IBKR_MARKET_DATA_TYPE = 1     # 1=Live, 2=Frozen, 3=Delayed
IBKR_CONNECT_ON_REQUEST = False
IBKR_FALLBACK_ON_SUBSCRIPTION_ERROR = True
```

---

## Red Flags (Escalate to Manual Review)

- 🚩 Security implications (API keys, credentials)
- 🚩 Data loss risk (deletion, corruption)
- 🚩 Production impact (if deployed)
- 🚩 Breaking API changes
- 🚩 External service interactions

When encountering red flags:
```markdown
⚠️ **CAUTION:** This issue involves [red flag type]

**Risk Assessment:**
- Impact: [description]
- Mitigation: [what's needed]

**Recommendation:** [Manual review / Backup first / Test environment]

Should I proceed or would you like to review first?
```

---

## Quick Reference - Common Fixes

### Connection Error Fix
```python
# Always ensure connection before operations
await self._ensure_connection()
```

### Subscription Error Fix
```python
# Use fallback configuration
if self._handle_subscription_error(error_msg, contract_info):
    continue  # Skip this contract, continue with others
```

### NaN Handling Fix
```python
# Always validate before conversion
if self._is_valid(val):
    return Decimal(str(val))
return None
```

### Async/Await Fix
```python
# Always await coroutines
result = await provider.get_data(symbol)  # Not: provider.get_data(symbol)
```

### Pydantic Validation Fix
```python
# Use proper model instantiation
return PriceQuote(
    symbol=symbol,
    last_price=self._to_decimal(ticker.last),
    timestamp=datetime.now(timezone.utc)
)
```

---

**Remember:** Efficiency through focus, quality through verification, clarity through documentation.
