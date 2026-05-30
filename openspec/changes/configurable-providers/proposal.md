## Why

Currently, the `ENABLED_PROVIDERS` environment variable enables LSEG (`lseg`), but the `DEFAULT_PRICE_PROVIDER` variable statically defaults to `ibkr`. This creates a configuration conflict when a user enables only one provider but the application expects a different one by default, leading to broken price endpoints unless explicitly specified in API requests. We need to resolve this so defaults dynamically respect the actually enabled providers.

## What Changes

- Dynamically validate and fallback provider defaults based on the `ENABLED_PROVIDERS` list during startup.
- Update `app/config.py` (or `registry.py`) to prevent setting a default provider that is not included in `ENABLED_PROVIDERS`.
- Log clear warnings/errors when an invalid configuration is detected.
- Ensure that if `ibkr` is requested as default but not enabled, a suitable fallback (like `lseg`) is used automatically.

## Capabilities

### New Capabilities
- `provider-fallback-logic`: Dynamic checking and resolution of default providers against the `ENABLED_PROVIDERS` configuration to prevent conflicting startup states.

### Modified Capabilities
- None.

## Impact

- **app/config.py**: Adjusted settings validation or post-initialization logic to align defaults.
- **app/providers/registry.py**: Initialization logic modified to reject or warn on invalid default providers.
- **Environment**: Startup behavior becomes safer and more resilient to user misconfigurations.