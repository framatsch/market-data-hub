## Context

In `app/config.py`, we define `ENABLED_PROVIDERS` (e.g. "lseg") and several default providers like `DEFAULT_PRICE_PROVIDER` (defaults to "ibkr"). When the application starts, `app/providers/registry.py` only initializes providers present in `ENABLED_PROVIDERS`. 
If an API endpoint does not explicitly request a provider, it uses the default (e.g. `DEFAULT_PRICE_PROVIDER`). If `ibkr` is the default but is not loaded (because only `lseg` is enabled), this causes an `InvalidProviderError` at runtime, effectively breaking the endpoint.

## Goals / Non-Goals

**Goals:**
- Ensure `DEFAULT_PRICE_PROVIDER`, `DEFAULT_COMPANY_PROVIDER`, and `DEFAULT_OPTIONS_PROVIDER` dynamically fall back to a loaded provider if their configured default is not in `ENABLED_PROVIDERS`.
- Prevent application crashes or 500 errors simply because a default provider is missing from the enabled list.
- Keep the fallback logic transparent and log a clear warning during startup so developers understand why the default was changed.

**Non-Goals:**
- We will not redesign the entire configuration system.
- We will not alter how providers themselves are initialized, just how the default is resolved when `get_price_provider(name=None)` is called.

## Decisions

**Decision 1: Resolve Defaults in `ProviderRegistry._initialize_providers`**
We will implement the fallback logic directly inside `ProviderRegistry._initialize_providers` in `app/providers/registry.py` right after loading the enabled providers. 
*Rationale:* This is the exact moment we know which providers successfully loaded. We can check if `settings.DEFAULT_PRICE_PROVIDER` is in `self._providers`. If not, we pick the first available provider from the loaded list that supports pricing, and override the default for the lifecycle of the application.
*Alternative:* Resolve it lazily inside `get_price_provider(name=None)`. This is less ideal because we want to log the warning exactly once at startup, not on every request.

**Decision 2: Update `settings` object dynamically at runtime or store resolved defaults in the registry?**
We will store the resolved defaults as instance variables on the `ProviderRegistry` (e.g. `self.default_price_provider`) and use those instead of referencing `settings.DEFAULT_PRICE_PROVIDER` directly during request time.
*Rationale:* Mutating the global `settings` object (which is a Pydantic `BaseSettings` instance) can have unintended side effects and goes against immutable config principles. Maintaining the "effective default" in the registry is cleaner.

## Risks / Trade-offs

- **Risk:** No suitable fallback provider is enabled at all (e.g. the user enabled *only* a provider that doesn't support options, but calls an options endpoint).
  **Mitigation:** The application will fail fast on startup or throw an `InvalidProviderError` as it does today, which is correct behavior if the requested capability doesn't exist.
- **Risk:** The "first available" fallback might pick a provider the user didn't expect.
  **Mitigation:** We will log a prominent `WARNING` during startup: "DEFAULT_PRICE_PROVIDER 'ibkr' is not enabled. Falling back to 'lseg'."