# configurable-providers Specification

## Purpose
Define how provider management is organized in the Admin UI: all provider-related configuration (runtime config, API keys, OAuth) is reached from the single `/admin/providers` page. Former standalone Credentials, Schwab Auth, and webhook/alert configuration pages were removed; Schwab token expiry is monitored via structured logs instead.

## Requirements

### Requirement: Provider Management Navigation
The provider management section SHALL be accessible exclusively at `/admin/providers`. The navigation SHALL NOT include separate entries for Credentials, Schwab Auth, or Alerts. All provider-related configuration (runtime config, API keys, OAuth) SHALL be accessible from the expanded provider accordion at `/admin/providers`.

#### Scenario: Single navigation entry for provider management
- **WHEN** the user views the sidebar
- **THEN** only "Providers" SHALL appear as the entry for provider-related management (no Credentials, Schwab Auth, or Alerts items)

#### Scenario: Full provider setup without page switching
- **WHEN** a user needs to configure a provider end-to-end (enable, set API keys, test connection)
- **THEN** all actions SHALL be completable within the single `/admin/providers` page without navigating elsewhere
