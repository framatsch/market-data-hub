## MODIFIED Requirements

### Requirement: SchwabProvider is options-capable
`SchwabProvider` SHALL satisfy `isinstance(provider, BaseOptionsProvider)` so the registry accepts it as an options provider.

#### Scenario: Registry accepts Schwab as options provider
- **WHEN** `registry.get_options_provider("schwab")` is called with Schwab loaded and enabled
- **THEN** a `SchwabProvider` instance SHALL be returned (no `InvalidProviderError`)
