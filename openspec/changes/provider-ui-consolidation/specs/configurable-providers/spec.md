## REMOVED Requirements

### Requirement: Webhook / Alert Configuration
**Reason**: Alert configuration via webhook is removed. Schwab token expiry monitoring is delegated to log-based infrastructure monitoring (Grafana/structured logging). There is no replacement UI for webhook configuration.

**Migration**: Users who configured a webhook URL should set up Grafana alerting rules based on the structured log output from the application. Log entries for Schwab token expiry are emitted at WARN level with field `event: schwab_token_expiry` and `days_remaining: N`.

### Requirement: Standalone Credentials Page
**Reason**: API key management is integrated into each Provider's Details panel (Authentication tab). A dedicated Credentials page is no longer needed.

**Migration**: Navigate to Providers → expand a provider → Authentication tab to manage API keys.

### Requirement: Standalone Schwab Auth Page
**Reason**: Schwab OAuth re-authorization is integrated into the Schwab provider's Authentication tab in the Provider Details panel. A dedicated Schwab Auth page is no longer needed.

**Migration**: Navigate to Providers → expand the Schwab provider → Authentication tab → click "Re-authorize".

## MODIFIED Requirements

### Requirement: Provider Management Navigation
The provider management section SHALL be accessible exclusively at `/admin/providers`. The navigation SHALL NOT include separate entries for Credentials, Schwab Auth, or Alerts. All provider-related configuration (runtime config, API keys, OAuth) SHALL be accessible from the expanded provider accordion at `/admin/providers`.

#### Scenario: Single navigation entry for provider management
- **WHEN** the user views the sidebar
- **THEN** only "Providers" SHALL appear as the entry for provider-related management (no Credentials, Schwab Auth, or Alerts items)

#### Scenario: Full provider setup without page switching
- **WHEN** a user needs to configure a provider end-to-end (enable, set API keys, test connection)
- **THEN** all actions SHALL be completable within the single `/admin/providers` page without navigating elsewhere
