## ADDED Requirements

### Requirement: Dynamic Provider Default Resolution
The `ProviderRegistry` SHALL dynamically resolve the default providers for prices, companies, and options during startup based on the loaded providers.

#### Scenario: Requested default is not enabled
- **WHEN** the `DEFAULT_PRICE_PROVIDER` is set to "ibkr" but "ibkr" is not in `ENABLED_PROVIDERS` (only "lseg" is enabled)
- **THEN** the registry MUST fall back to "lseg" as the default price provider
- **AND** the registry MUST log a `WARNING` indicating the fallback.

#### Scenario: Requested default is enabled
- **WHEN** the `DEFAULT_PRICE_PROVIDER` is set to "ibkr" and "ibkr" IS in `ENABLED_PROVIDERS`
- **THEN** the registry MUST use "ibkr" as the default price provider.

#### Scenario: No suitable fallback available
- **WHEN** a provider default is requested (e.g. `DEFAULT_OPTIONS_PROVIDER`) but none of the enabled providers support that capability
- **THEN** the registry SHALL NOT set a fallback (or set it to `None`), and subsequent requests to that capability SHALL throw an `InvalidProviderError`.

### Requirement: Registry State Source of Truth
The API routes SHALL use the resolved default providers from the `ProviderRegistry` instance, rather than reading directly from the global `settings` object.

#### Scenario: Endpoint calls for default provider
- **WHEN** an endpoint calls `registry.get_price_provider(name=None)`
- **THEN** the registry MUST return the instance of the dynamically resolved default provider.