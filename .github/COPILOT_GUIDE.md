# 🤖 Copilot Configuration Guide

This directory contains specialized instructions and agent modes for GitHub Copilot to optimize bug fixing and feature development in the Market Data Hub project (FastAPI + IBKR + LSEG).

## 📂 File Structure

### Copilot Instructions (Auto-loaded)
Copilot automatically reads these files and applies them to all conversations:

- **`copilot-instructions.md`** ⭐ START HERE
  - Complete technical reference for the project
  - Error pattern recognition (9 main patterns - IBKR + LSEG)
  - Technology-specific behaviors (FastAPI, ib_async, refinitiv.data, Pydantic)
  - Quick Fix Mode and Debug Mode workflows
  - Decision trees and debugging strategies
  - **Use:** Copilot reads this automatically
  - **Size:** ~25 KB, comprehensive coverage

### Agent Modes (Specialized Workflows)
Located in `.github/agents/` directory:

#### Quick Fix Agent
- **`quickfix.agent.md`**
  - For rapid error resolution
  - Use when: Clear error + known pattern
  - Expected time: 2-3 minutes
  - Target tokens: <5k per fix
  - Best for: Known error patterns, obvious fixes

#### Debug Agent
- **`debug.agent.md`**
  - For systematic problem analysis
  - Use when: Intermittent/complex issues
  - Expected time: 20-30 minutes
  - 7-phase systematic workflow
  - Requires user approval before commit
  - Best for: Complex issues, integration problems

#### Plan Feature Agent
- **`plan.agent.md`**
  - For interactive feature specification generation
  - Use when: New feature request, need technical spec
  - Expected time: 15-30 minutes (10-15 questions)
  - One question at a time with options (A/B/C/D)
  - Generates `specs/XX.prompt.md` files
  - Best for: New features, complex enhancements

#### Implement Feature Agent
- **`implement.agent.md`**
  - For automated feature implementation from specs
  - Use when: Have `specs/XX.prompt.md` ready to implement
  - Expected time: 1-3 hours (depends on phases)
  - Phase-by-phase commits with testing
  - Interactive or Auto mode
  - Best for: Systematic feature development with git workflow

## 🚀 Quick Start

### Step 1: Copilot Instructions Auto-load
VS Code automatically uses `copilot-instructions.md` if it's in `.github/`

### Step 2: Select Your Workflow Mode

**For Clear Errors (Quick Fix):**
```
@workspace Quick Fix Mode
❌ [Paste your error traceback with line number]
```

Expected response: 2-3 minute turnaround with immediate fix application.

**For Complex Issues (Debug):**
```
@workspace Debug Mode
Problem: [Describe issue]
When: [Always/Sometimes/After change]
```

Expected response: Systematic investigation through 7 phases.

**For New Features (Plan Feature):**
```
@workspace Plan Feature Mode
Feature: [Describe what you want to build]
```

Expected response: Interactive Q&A session (10-15 questions), generates `specs/XX.prompt.md`.

**For Feature Implementation (Implement Feature):**
```
@workspace Implement Feature Mode
Spec: specs/01.prompt.md
```

Expected response: Phase-by-phase implementation with commits, tests, and documentation.

## 📋 Error Patterns Reference

Quick lookup for the main error patterns included in copilot-instructions.md:

### IBKR Patterns

### Pattern 1: IBKR Connection Errors
```
Error: ProviderConnectionError: Could not connect to IBKR
Files: app/providers/ibkr.py - _ensure_connection()
Root Cause: TWS/Gateway not running or wrong port/host
Fix: Check TWS/Gateway is running, verify port (4001/7497)
Code: await self.ib.connectAsync(self.host, self.port, self.client_id)
```

### Pattern 2: Market Data Subscription (Error 10091)
```
Error: Error 10091: No market data subscription
Files: app/providers/ibkr.py - _get_tickers_snapshot()
Root Cause: Missing market data subscription for instrument
Fix: Use fallback_on_subscription_error=True for graceful degradation
Code: if self._handle_subscription_error(error_msg, contract_info): continue
```

### Pattern 3: Contract Qualification Failures
```
Error: Contract not found or empty contract details
Files: app/providers/ibkr.py - get_option_chain(), get_last_price()
Root Cause: Invalid symbol, exchange, or contract parameters
Fix: Always qualify contracts before requesting data
Code: qualified = await self.ib.qualifyContractsAsync(contract)
```

### Pattern 4: Async/Await Misuse
```
Error: RuntimeWarning: coroutine was never awaited
Files: app/api/routes_*.py, app/providers/*.py
Root Cause: Missing await or blocking call in async context
Fix: Always await coroutines, use asyncio.sleep() not time.sleep()
Code: result = await provider.get_data(symbol)
```

### Pattern 5: Pydantic Validation Errors
```
Error: ValidationError: X validation errors for Model
Files: app/models/*.py, app/api/routes_*.py
Root Cause: Missing required fields or wrong types in responses
Fix: Always return Pydantic models, use Optional[T] for nullable fields
Code: return PriceQuote(symbol=symbol, last_price=Decimal(...))
```

### Pattern 6: NaN/None Handling
```
Error: ValueError or incorrect calculations with NaN
Files: app/providers/ibkr.py - _to_decimal(), _is_valid()
Root Cause: IBKR returns NaN for unavailable data, not None
Fix: Check for NaN as well as None before conversion
Code: if self._is_valid(val): return Decimal(str(val))
```

### LSEG/Refinitiv Patterns

### Pattern 7: LSEG Session Errors
```
Error: RDError or session not authenticated
Files: app/providers/lseg.py - _get_session()
Root Cause: Session not initialized or credentials invalid
Fix: Initialize session with credentials, set as default
Code: session = rd.session.platform.Definition(...).get_session()
```

### Pattern 8: Ticker to RIC Conversion
```
Error: RIC not found or empty search results
Files: app/providers/lseg.py - _ticker_to_ric()
Root Cause: Invalid ticker or search filter mismatch
Fix: Use search.Definition() to convert ticker → RIC
Code: response = search.Definition(query=ticker, filter=f"TickerSymbol eq '{ticker}'").get_data()
```

### Pattern 9: Data Parsing Errors
```
Error: KeyError on DataFrame columns
Files: app/providers/lseg.py - data parsing methods
Root Cause: Unexpected response structure or missing columns
Fix: Check df.empty and column existence before accessing
Code: if col in df.columns: value = df[col].iloc[0]
```

## 🎯 Decision Tree: When to Use Which Mode

```
Is this a new feature request?
├─ Yes → Use Plan Feature Mode → Generate spec → Use Implement Feature Mode
└─ No → Is it a bug/error?
    ├─ Yes → Is error message clear and complete with line number?
    │  ├─ Yes → Is it a known pattern? (see 6 patterns above)
    │  │  ├─ Yes → Use Quick Fix Mode (2-3 min)
    │  │  └─ No → Is fix obvious from traceback?
    │  │     ├─ Yes → Use Quick Fix Mode (2-3 min)
    │  │     └─ No → Use Debug Mode (20-30 min)
    │  └─ No (unclear) → Use Debug Mode
    └─ No → Use Debug Mode

Is problem intermittent or data-dependent?
├─ Yes → Use Debug Mode
└─ No → Use Quick Fix Mode

Multiple components affected or unclear interaction?
├─ Yes → Use Debug Mode
└─ No → Use Quick Fix Mode

Do you have a specs/XX.prompt.md file ready to implement?
├─ Yes → Use Implement Feature Mode
└─ No → Use Plan Feature Mode first
```

## ✅ User Approval Workflow

**IMPORTANT:** Copilot NEVER commits without your explicit approval!

```
Workflow:
1. AI analyzes and fixes the issue
2. AI provides fix and asks for approval
3. You respond:
   - "✅" or "Yes" → AI commits automatically
   - "❌" or "No, still error XYZ" → AI re-analyzes

Approval Required For:
- Bug fixes
- Refactoring
- Performance optimizations
- New features
- Any code changes

Auto-commit Policy:
- Never (all changes require explicit user approval)
```

## 🔧 Technology Stack Reference

### FastAPI Framework (Primary)
- **Key Patterns:**
  - `@router.get("/endpoint", response_model=Model)` - Route definition
  - `async def handler(...)` - All handlers are async
  - `Depends(get_provider)` - Dependency injection
  - `AppError` exception hierarchy with HTTP status mapping
- **Entry Point:** `app/main.py`
- **Routing:** `app/api/routes_*.py` files

### ib_async Library (IBKR Provider)
- **Key Operations:**
  - `ib.connectAsync(host, port, client_id)` - Non-blocking connect
  - `ib.qualifyContractsAsync(contract)` - Validate contract
  - `ib.reqMktData(contract)` - Request market data
  - `ib.reqHistoricalDataAsync(...)` - Historical data
- **Connection State:** Always check `ib.isConnected()`
- **Error Handling:** Error 10091 is subscription warning, not fatal
- **File:** `app/providers/ibkr.py`

### refinitiv.data Library (LSEG Provider)
- **Key Operations:**
  - `rd.session.platform.Definition()` - Create session
  - `session.open()` - Open authenticated session
  - `rd.session.set_default(session)` - Set default session
  - `search.Definition()` - Search and convert ticker → RIC
  - `historical_pricing.summaries.Definition()` - Get historical data
- **Session Management:** Synchronous with credential-based auth
- **Response Format:** Returns pandas DataFrame in response.data.df
- **File:** `app/providers/lseg.py`
- **Environment Variables:** `LSEG_APP_KEY`, `LSEG_USERNAME`, `LSEG_PASSWORD`

### Pydantic Models
- **Key Patterns:**
  - `class Model(BaseModel)` - All models inherit BaseModel
  - `Optional[T] = None` - Nullable fields
  - `Decimal` for financial values, not `float`
  - `datetime` with timezone awareness
- **Location:** `app/models/*.py`

### Error Handling
- **Base Class:** `AppError(message, code, details)`
- **HTTP Mapping:** In `app/main.py` exception handler
- **Codes:** `DATA_NOT_FOUND` (404), `INVALID_PROVIDER` (400), `PROVIDER_TIMEOUT` (503)
- **File:** `app/utils/errors.py`

## 📊 Project Context

- **Architecture:** FastAPI REST/WebSocket API with provider abstraction
- **Primary Provider:** IBKR via `ib_async` library (async)
- **Secondary Provider:** LSEG via `refinitiv.data` SDK (sync)
- **Data Types:** Price quotes, historical bars, option chains, company data
- **Deployment:** Docker + Kubernetes ready
- **Testing:** Integration tests in `tests/integration/`

## 📁 Project Structure

```
market-data-hub/
├── app/
│   ├── main.py                  # FastAPI app entry point
│   ├── config.py                # Environment settings
│   ├── dependencies.py          # Provider dependency injection
│   ├── api/
│   │   ├── routes_meta.py       # Health check endpoints
│   │   ├── routes_prices.py     # Price data endpoints
│   │   ├── routes_companies.py  # Company data endpoints
│   │   ├── routes_options.py    # Options chain endpoints
│   │   └── routes_ws.py         # WebSocket streaming
│   ├── models/                  # Pydantic data models
│   ├── providers/               # IBKR, LSEG implementations
│   ├── services/                # Business logic orchestration
│   └── utils/                   # Errors, logging utilities
├── tests/integration/           # Integration tests
├── k8s/                         # Kubernetes manifests
├── specs/                       # Feature specifications
├── .github/
│   ├── copilot-instructions.md  # Main instructions (auto-loaded)
│   ├── COPILOT_GUIDE.md         # This file
│   └── agents/                  # Workflow agents
├── Dockerfile                   # Container build
├── pyproject.toml               # Python dependencies
└── README.md                    # Project documentation
```

## ✅ Best Practices

### For Quick Fix Mode
- ✅ Provide complete error traceback (full stack trace)
- ✅ Include exact file path and line number
- ✅ Keep description brief (1-2 sentences)
- ✅ Wait for AI to apply fix
- ❌ Don't provide multiple choice options
- ❌ Don't ask "what should I do?" (AI decides)

### For Debug Mode
- ✅ Describe the problem clearly (1-2 sentences)
- ✅ Include when it happens (Always/Sometimes/After change)
- ✅ Provide any relevant error output
- ✅ Follow AI's investigation steps
- ✅ Approve explicitly after verification
- ❌ Don't rush the diagnosis (20-30 min expected)

### For Plan Feature Mode
- ✅ Answer questions one at a time (A/B/C/D)
- ✅ Ask clarifications when needed
- ✅ Review generated spec before implementation
- ✅ Save spec to `specs/XX.prompt.md`
- ❌ Don't skip questions (each drives decisions)
- ❌ Don't treat clarifications as option selections

### For Implement Feature Mode
- ✅ Ensure specs/XX.prompt.md exists first
- ✅ Choose Interactive (learning) or Auto (speed) mode
- ✅ Test after each phase before approving
- ✅ Review commit messages
- ✅ Verify all tests pass
- ❌ Don't skip phases
- ❌ Don't commit broken code

### For All Modes
- ✅ Test changes before approving
- ✅ Approve explicitly with "✅" before commit
- ✅ Report if fix doesn't work
- ✅ Check related code when AI suggests it
- ❌ Never force commits (AI won't without approval)

## 💡 Example Interactions

### Example 1: Quick Fix Mode
```
USER:
@workspace Quick Fix Mode
❌ ProviderConnectionError: Could not connect to IBKR
File "app/providers/ibkr.py", line 120
await self.ib.connectAsync(self.host, self.port, self.client_id)

COPILOT:
Root Cause: TWS/Gateway not running or connection refused

Fix: Verify IBKR Gateway/TWS is running and port is correct
[Shows troubleshooting steps and config verification]

✅ This is a configuration issue. Please check:
1. TWS/Gateway is running
2. Port 4001 (Gateway) or 7497 (TWS Paper) is correct
3. API connections are enabled in TWS settings
```

### Example 2: Debug Mode
```
USER:
@workspace Debug Mode
Problem: Option chain returns empty sometimes
When: Only for some symbols, intermittent
Happens: ~30% of requests fail

COPILOT:
[Phase 1: Characterization - 2-3 min]
[Phase 2: Investigation - 5-10 min]
[Phase 3: Solution Design - 3-5 min]
[Phase 4: Implementation - Apply fix]
[Phase 5: Verification - Test cases]
[Phase 6: Follow-up - Related issues]
[Phase 7: Closure - Final report]

Commit approved?

USER: ✅

COPILOT: [Commits with comprehensive explanation]
```

### Example 3: Plan Feature Mode
```
USER:
@workspace Plan Feature Mode
Feature: Add caching layer for price quotes

COPILOT:
## 🎯 Question 1/12: Cache Strategy

What caching approach should be used?

**Options:**
- **A) In-memory (dict/TTLCache)**
- **B) Redis**
- **C) Both (tiered)**
- **D) No cache, optimize provider**

**Suggested:** A) In-memory (simplest, no external dependency)

**Examples:**
- A: TTLCache with 5-second expiry for quotes
- B: Redis with pub/sub for invalidation

**Context:** Price data is time-sensitive, short TTL needed

---

**Which option? (A/B/C/D)**

USER: A

COPILOT:
✅ In-memory caching selected

## 🎯 Question 2/12: Cache Invalidation
[Next question...]

[After 12 questions...]

## 🎉 Feature Planning Complete!

**📄 Generated:** `specs/02.prompt.md` - Price Quote Caching
**🌿 Feature Branch:** `feature/price-caching`

**🚀 Next Step:** Begin implementation with Implement Feature mode!
```

### Example 4: Implement Feature Mode
```
USER:
@workspace Implement Feature Mode
Spec: specs/02.prompt.md

COPILOT:
## 🔍 Pre-Flight Checks
✅ Specification exists: specs/02.prompt.md
✅ Git clean
✅ Feature branch: feature/price-caching

## 🎮 Implementation Mode Selection
**Your choice (A/B):**

USER: A (Interactive)

COPILOT:
## 🌿 Feature Branch Created
✅ Switched to: feature/price-caching

## 🔨 Phase 1/6: Cache Module Setup
**Checklist:**
- [ ] Create app/utils/cache.py
- [ ] Implement TTLCache wrapper
- [ ] Add configuration options

[Implements code...]

## 📋 Phase 1 Complete - Review
**Files Created:** app/utils/cache.py (85 lines)
**Errors:** None ✅

**Ready to commit Phase 1?** (yes/no/review)

USER: yes

COPILOT:
✅ Committed: Phase 1: Cache Module Setup

## 🔨 Phase 2/6: Provider Integration
[Continues through all phases...]
```

## 📚 Related Documentation

- `../../README.md` - Project overview and setup
- `../../ARCHITECTURE_OVERVIEW.md` - Architecture diagrams
- `../../specs/` - Feature specifications

## 🔗 Integration Points

### Copilot Auto-loads
- `copilot-instructions.md` is automatically loaded by VS Code Copilot
- Applies all error patterns and technical knowledge to conversations
- Works without any user configuration

### Agent Activation
- Use `@workspace Quick Fix Mode` or `@workspace Debug Mode` to activate
- Or reference specific files to trigger contextual help
- Chat modes are optional (instructions always active)

## ❓ FAQ

**Q: How do I use these instructions and agents?**
A: Copilot loads instructions automatically. For agents, start your chat with "@workspace Quick Fix Mode" or "@workspace Debug Mode".

**Q: What if my error isn't in the 6 patterns?**
A: Use Debug Mode - it's flexible and systematic. New patterns will be added to instructions as discovered.

**Q: Do I have to use Quick Fix or Debug modes?**
A: No - they're optional. The copilot-instructions.md is always active regardless. Chat modes just guide the interaction style.

**Q: When should I use Plan Feature vs just describing what I want?**
A: Use Plan Feature mode when you want a structured spec with implementation checklist. For quick changes, describe directly. Plan Feature creates `specs/XX.prompt.md` for systematic implementation.

**Q: Can I implement without using Plan Feature mode first?**
A: Yes for small changes. For larger features, Plan Feature generates proper specs that Implement Feature mode can execute systematically with git workflow.

**Q: What's the difference between Interactive and Auto mode in Implement Feature?**
A: Interactive shows code preview and asks approval after each phase (learning, complex features). Auto implements all phases automatically (speed, well-defined specs).

**Q: Can I modify these files?**
A: Yes! Update them as you discover new patterns or improve workflows.

**Q: What if a fix doesn't work?**
A: Report back with the error. AI will re-analyze using Debug Mode techniques.

**Q: Why are error patterns in instructions separate from agents?**
A: Instructions provide background knowledge (always active). Agents guide interaction style (user-selectable). Together they provide both depth and flexibility.

**Q: Does AI commit without my approval?**
A: Absolutely not. All changes require explicit ✅ approval before commit.

---

**Version:** 2.0 (with LSEG/Refinitiv)
**Last Updated:** 2025-12-25
**Project:** Market Data Hub (FastAPI + IBKR + LSEG/Refinitiv)

**Key Documents in This Directory:**
- `copilot-instructions.md` - Comprehensive technical reference (primary)
- `agents/quickfix.agent.md` - Quick fix workflow (2-3 min)
- `agents/debug.agent.md` - Debug workflow (7 phases, 20-30 min)
- `agents/plan.agent.md` - Feature planning workflow (15-30 min)
- `agents/implement.agent.md` - Feature implementation workflow (1-3 hours)
