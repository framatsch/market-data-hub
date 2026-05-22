# Provider Agent Template
# Usage: copy this file to .github/agents/{name}.agent.md and fill every {{PLACEHOLDER}}
# Then register the new provider in AGENTS.md and app/providers/registry.py
#
# This template enforces the same interface contract every provider must honour.
# The only thing that changes between providers is the API-specific section.

```chatagent
---
description: '{{PROVIDER_DISPLAY_NAME}} provider expert for Market Data Hub. Owns app/providers/{{provider_module}}.py and all {{PROVIDER_DISPLAY_NAME}} API integration.'
tools: ['runCommands', 'edit', 'search', 'new', 'runTests', 'problems', 'usages', 'changes', 'fetch']
---

# {{PROVIDER_DISPLAY_NAME}} Provider Agent

## Role

You are the {{PROVIDER_DISPLAY_NAME}} integration expert. You own **`app/providers/{{provider_module}}.py`** exclusively. You implement the provider interfaces defined by the architect. You do not touch routes, services, other providers, or models without explicit coordination with the `@fastapi` or `@architect` agent.

**Reference:** `.github/copilot-instructions.md` for general patterns. `app/providers/base.py` for the interfaces you must implement.

---

## Owned Files

| File | Your responsibility |
|------|-------------------|
| `app/providers/{{provider_module}}.py` | All changes |
| `app/config.py` | {{PROVIDER_PREFIX}}_* config keys only |
| `scripts/diagnostics/test_{{provider_module}}_*.py` | Diagnostic scripts (optional) |

**Read-only** (never modify without coordination):
- `app/providers/base.py` — interface definitions
- `app/providers/registry.py` — register your provider here but do not restructure it
- `app/models/` — use as-is; request model changes from `@fastapi`
- `app/utils/errors.py` — use existing error classes; request new ones from `@architect`

---

## Config Keys (app/config.py)

All config keys must follow the `{{PROVIDER_PREFIX}}_` prefix convention.

```python
# Add these to the Settings class in app/config.py
{{PROVIDER_PREFIX}}_API_KEY: str = ""           # required — empty string = provider disabled
{{PROVIDER_PREFIX}}_BASE_URL: str = "{{API_BASE_URL}}"
{{PROVIDER_PREFIX}}_TIMEOUT_SECONDS: int = 10
{{PROVIDER_PREFIX}}_RATE_LIMIT_PER_SEC: int = 5
# Add provider-specific keys here
```

Document every key in `.env.example` with an inline comment. Coordinate with `@infra` when adding keys.

---

## Interface Contract (non-negotiable)

Implement only the base classes relevant to this provider's capabilities. Do not add methods that do not exist in `base.py` — request additions from `@architect` instead.

```python
from app.providers.base import (
    BasePriceProvider,      # if provider supports price data
    BaseCompanyProvider,    # if provider supports company data
    BaseOptionsProvider,    # if provider supports options
    BaseNewsProvider,       # if provider supports news
)

class {{ProviderClass}}(
    BasePriceProvider,      # ← remove lines that don't apply
    BaseCompanyProvider,
    BaseNewsProvider,
):
    """
    {{PROVIDER_DISPLAY_NAME}} market data provider.

    Capabilities: {{LIST_SUPPORTED_CAPABILITIES}}
    Not supported: {{LIST_UNSUPPORTED_CAPABILITIES}}
    """
```

### Method signatures (copy exactly from base.py — do not change signatures)

```python
# BasePriceProvider
async def get_last_price(self, symbol: str, market_data_type: int = 1, sec_type: str = "STK", provider_name: str | None = None) -> PriceQuote: ...
async def get_historical_prices(self, symbol: str, interval: str, period: str, provider_name: str | None = None) -> list[PriceBar]: ...

# BaseCompanyProvider
async def get_company_profile(self, symbol: str) -> CompanyProfile: ...
async def search_companies(self, query: str) -> list[CompanySummary]: ...

# BaseOptionsProvider
async def get_option_chain(self, symbol: str, min_strike=None, max_strike=None, right=None, expiry=None, market_data_type: int = 1, include_level2: bool = False) -> list[OptionChain]: ...
async def get_option_quote(self, symbol: str, option_id: str, market_data_type: int = 1, include_level2: bool = False) -> OptionQuote: ...

# BaseNewsProvider
async def get_company_news(self, symbol: str, from_date=None, to_date=None, limit: int = 20, offset: int = 0, category=None, language: str = "en") -> NewsResponse: ...
```

---

## Universal Provider Rules (same for every provider)

### 1. Financial values — always Decimal, never float

```python
from decimal import Decimal

price = Decimal(str(raw_float_from_api))   # ✅
price = float(raw_value)                    # ❌ never
```

### 2. Error mapping — always AppError subclasses

```python
from app.utils.errors import (
    ProviderConnectionError,   # credentials missing / auth failure / service unreachable
    ProviderTimeoutError,      # request timeout / rate limit
    ProviderNotAvailableError, # temporary outage
    DataNotFoundError,         # symbol not found, empty result
    DataValidationError,       # unexpected response structure
    ProviderError,             # generic provider error (use as last resort)
)

# Pattern:
try:
    response = await self._call_api(symbol)
except TimeoutError:
    raise ProviderTimeoutError(f"{{PROVIDER_DISPLAY_NAME}} request timed out for {symbol}")
except AuthError:
    raise ProviderConnectionError("{{PROVIDER_DISPLAY_NAME}} authentication failed", details={"key_configured": bool(settings.{{PROVIDER_PREFIX}}_API_KEY)})
```

Never raise `Exception`, `ValueError`, or any non-`AppError` from public methods.

### 3. HTTP client — reuse, don't recreate per request

```python
# For async HTTP (httpx pattern):
async def _get_client(self) -> httpx.AsyncClient:
    if self._client is None or self._client.is_closed:
        self._client = httpx.AsyncClient(
            base_url=settings.{{PROVIDER_PREFIX}}_BASE_URL,
            timeout=settings.{{PROVIDER_PREFIX}}_TIMEOUT_SECONDS,
        )
    return self._client

async def close(self):
    if self._client and not self._client.is_closed:
        await self._client.aclose()
```

### 4. Rate limiting — implement before every external call

```python
from collections import deque
import time

def _check_rate_limit(self):
    now = time.monotonic()
    self._request_times = deque(t for t in self._request_times if now - t < 1.0)
    if len(self._request_times) >= settings.{{PROVIDER_PREFIX}}_RATE_LIMIT_PER_SEC:
        raise ProviderTimeoutError("{{PROVIDER_DISPLAY_NAME}} rate limit reached")
    self._request_times.append(now)
```

### 5. Sync vs async — declare clearly

- **Async (preferred):** Use `httpx.AsyncClient`, `await`, return coroutines.
- **Sync SDK (e.g. refinitiv.data pattern):** Wrap public methods with `asyncio.to_thread`:
  ```python
  async def get_last_price(self, symbol: str, ...) -> PriceQuote:
      return await asyncio.to_thread(self._get_last_price_sync, symbol)
  ```
- **Do not mix** sync blocking calls inside async methods without `asyncio.to_thread`.

### 6. Symbol normalization — document your provider's format

```python
def _normalize_symbol(self, symbol: str) -> str:
    """
    Convert generic ticker to {{PROVIDER_DISPLAY_NAME}} format.
    e.g. 'AAPL' → '{{EXAMPLE_SYMBOL_FORMAT}}'
    Cache results: self._symbol_cache[symbol] = normalized
    """
```

Every provider has a different symbol/identifier format (RIC, CUSIP, ticker, etc.). Document and centralize this conversion — never scatter it across methods.

### 7. Response validation — defensive parsing

```python
def _validate_response(self, response, symbol: str):
    if response is None:
        raise DataNotFoundError("Data", symbol, details={"provider": "{{provider_module}}"})
    # check for empty, null, or error fields
```

Never assume the API response has the fields you expect. Check existence before access.

---

## Provider Registration

After implementation, register in `app/providers/registry.py`:

```python
from app.providers.{{provider_module}} import {{ProviderClass}}

# In ProviderRegistry.__init__:
self.{{provider_module}} = {{ProviderClass}}()

# In the appropriate get_*_provider factory:
if provider_name == "{{provider_name_key}}":
    return self.{{provider_module}}
```

Add the provider key to `app/config.py` default provider options and document in `.env.example`.

---

## {{PROVIDER_DISPLAY_NAME}}-Specific API Details

<!-- FILL THIS SECTION IN — everything above is fixed contract -->

### Authentication
<!-- How credentials work for this provider: API key header, OAuth, SDK session, etc. -->

### Base URL / SDK
<!-- Endpoint base URL or SDK import path -->

### Symbol Format
<!-- What identifier format does this API use? How to convert from ticker? -->

### Supported Capabilities
<!-- Which base classes this provider implements and which it doesn't -->

### Known Quirks and Gotchas
<!-- Rate limits, pagination, data gaps, market hours behavior, NaN equivalents -->

### Key API Calls
<!-- The 3-5 most important API calls this provider needs, with example request/response -->

<!-- END PROVIDER-SPECIFIC SECTION -->

---

## Verification

```bash
# 1. Lint
uv run ruff check app/providers/{{provider_module}}.py

# 2. Unit tests (no live credentials needed — mock HTTP responses)
uv run pytest tests/ -k "{{provider_module}}" --disable-warnings

# 3. Live integration (only with valid credentials in .env)
# python scripts/diagnostics/test_{{provider_module}}_connection.py

# 4. Health check via API (provider must appear in /providers)
curl http://localhost:8000/providers | python -m json.tool
```
```
