# OpenSpec: Configurable Provider Loading

## Status
- **Type**: Feature / Refactoring
- **Status**: Proposed
- **Author**: Gemini CLI
- **Date**: 2026-05-30

## Context & Problem
Currently, the `ProviderRegistry` attempts to initialize all available providers (`ibkr`, `lseg`, `schwab`, `finnhub`, `mock`) at startup. While recent changes made this initialization resilient to missing dependencies (ImportErrors), there is no way for a user to explicitly disable a provider they don't want to use or to limit the application to a specific subset.

## Proposed Change
Introduce an environment variable `ENABLED_PROVIDERS` that allows users to specify a comma-separated list of providers to load.

### Requirements
1. **Default Behavior**: If `ENABLED_PROVIDERS` is not set or empty, all available providers should be attempted to be loaded (current behavior).
2. **Filtering**: If `ENABLED_PROVIDERS` is set (e.g., `lseg,ibkr`), only the specified providers should be initialized.
3. **Resilience**: The registry should still handle cases where a requested provider fails to initialize (e.g., missing library) gracefully with a warning.
4. **Validation**: Invalid provider names in the list should be ignored or logged as a warning.

## Technical Design

### 1. Configuration (`app/config.py`)
Add `ENABLED_PROVIDERS` to the `Settings` class.

```python
class Settings(BaseSettings):
    # ...
    ENABLED_PROVIDERS: str = ""  # Empty string means all
```

### 2. Registry Logic (`app/providers/registry.py`)
Modify `_initialize_providers` to parse the configuration and filter the loading process.

```python
def _initialize_providers(self):
    all_available = {
        "ibkr": IBKRProvider,
        "lseg": LSEGProvider,
        "schwab": SchwabProvider,
        "finnhub": FinnhubProvider,
        "mock": MockNewsProvider,
    }
    
    # Parse enabled providers
    enabled_str = settings.ENABLED_PROVIDERS.strip()
    if enabled_str:
        enabled_list = [p.strip().lower() for p in enabled_str.split(",")]
        # Filter to only requested and valid names
        to_load = {name: cls for name, cls in all_available.items() if name in enabled_list}
    else:
        to_load = all_available

    for name, cls in to_load.items():
        try:
            self._providers[name] = cls()
        except ImportError as e:
            logger.warning(f"Provider '{name}' not available: {e}")
        except Exception as e:
            logger.error(f"Failed to initialize provider '{name}': {e}")
```

### 3. Startup Protocol (`app/main.py`)
The existing startup protocol will automatically reflect the loaded providers since it pulls from `registry._providers.keys()`.

## Verification Plan
1. **Manual Test (All)**: Run with `ENABLED_PROVIDERS=""` and verify all successful providers appear in the startup protocol.
2. **Manual Test (Subset)**: Run with `ENABLED_PROVIDERS="lseg,finnhub"` and verify only these two (if available) appear.
3. **Manual Test (Invalid)**: Run with `ENABLED_PROVIDERS="lseg,invalid_name"` and verify `lseg` loads and `invalid_name` is ignored.
