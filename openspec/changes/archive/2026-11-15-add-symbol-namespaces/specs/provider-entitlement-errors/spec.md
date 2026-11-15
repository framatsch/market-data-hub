## ADDED Requirements

### Requirement: Uniform not-entitled error
The system SHALL provide `ProviderNotEntitledError` with error code `PROVIDER_NOT_ENTITLED`, mapped to HTTP 403. Its details SHALL include `provider`, the canonical `symbol`, the queried native `instrument` when known, and `provider_message` (the provider's error text, truncated to 500 characters). Every provider SHALL raise this error for prices, options and volatility when the provider denies access because of a missing market-data entitlement or subscription. MCP tools SHALL return the same error code. The error message SHALL state that the provider subscription does not cover the instrument, so it is not confused with hub authentication.

#### Scenario: Error shape
- **WHEN** a provider denies `I:SPX` because of a missing subscription
- **THEN** the response is HTTP 403 with code `PROVIDER_NOT_ENTITLED` and `details.provider`, `details.symbol` `I:SPX` and `details.provider_message`

#### Scenario: MCP
- **WHEN** an MCP tool call hits a missing entitlement
- **THEN** the tool error carries code `PROVIDER_NOT_ENTITLED`

### Requirement: Runtime detection, no hard-coded subscriptions
Entitlement SHALL be determined only from provider responses at request time. The hub SHALL NOT keep static lists of subscribed instruments or plans. Detection rules:
- Polygon: HTTP 403 or a `NOT_AUTHORIZED` status in the response body.
- LSEG: `UserNotPermission`, "user has no permission", "user does not have permission" or "insufficient scope".
- IBKR: error codes 354 and 10089, and 10091 when no configured fallback applies.
- Schwab and Prixe: HTTP 403 responses that are not token or credential failures. Credential failures (HTTP 401, or a Schwab token rejection) SHALL keep mapping to `PROVIDER_NOT_AVAILABLE`.

#### Scenario: Subscription upgrade takes effect immediately
- **WHEN** a request returned `PROVIDER_NOT_ENTITLED` and the user then upgrades the provider subscription
- **THEN** the next identical request calls the provider again and returns data, because errors are never cached

#### Scenario: Credential failure is not an entitlement error
- **WHEN** Prixe answers HTTP 401
- **THEN** the system responds with `PROVIDER_NOT_AVAILABLE`, not `PROVIDER_NOT_ENTITLED`

### Requirement: Configured degradation precedes entitlement errors
When a provider has a configured fallback for missing entitlements, the fallback SHALL be applied first. `PROVIDER_NOT_ENTITLED` SHALL only be raised when the fallback is disabled or also fails. Examples: IBKR `IBKR_FALLBACK_ON_SUBSCRIPTION_ERROR` to delayed data, and Polygon previous close for restricted NBBO.

#### Scenario: IBKR delayed fallback
- **WHEN** IBKR reports 10089 for live data and `IBKR_FALLBACK_ON_SUBSCRIPTION_ERROR` is `true`
- **THEN** delayed data is returned as today

#### Scenario: IBKR without fallback
- **WHEN** IBKR reports 354 and no fallback applies
- **THEN** the system responds with HTTP 403 `PROVIDER_NOT_ENTITLED`
