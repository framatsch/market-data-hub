## MODIFIED Requirements

### Requirement: Token management errors surface as ProviderConnectionError
The system SHALL catch all `schwab-py` authentication and token-related errors and re-raise them as `ProviderConnectionError` with a human-readable hint. When a 401 or 403 response is received AND the client was previously initialized (indicating a refresh token expiry rather than initial misconfiguration), the provider SHALL additionally set `_paused = True` and fire an async webhook notification before raising. When `_paused` is `True`, the provider SHALL raise `ProviderConnectionError` immediately on any subsequent call without attempting any network request.

#### Scenario: Initial auth failure (client was None)
- **WHEN** `SCHWAB_API_KEY` is set but credentials are invalid and client has never been initialized
- **THEN** `ProviderConnectionError` is raised with message indicating auth failure; `_paused` remains `False`

#### Scenario: Refresh token expiry (client was not None) — pauses provider
- **WHEN** a live request returns 401 after the provider was previously working (client was not None)
- **THEN** `_paused = True`, `_client = None`, `ProviderConnectionError` is raised, and webhook is fired if `SCHWAB_ALERT_WEBHOOK_URL` is set

#### Scenario: Paused provider rejects calls immediately
- **WHEN** `SchwabProvider._paused = True` and any price method is called
- **THEN** `ProviderConnectionError` is raised immediately without any HTTP call to Schwab

#### Scenario: Provider unpaused after re-auth
- **WHEN** `POST /api/admin/schwab/auth/callback` successfully completes
- **THEN** `_paused = False`, `_client = None`, and the next call to any price method proceeds normally via `_get_client()`

#### Scenario: Rate limit error surfaces as ProviderTimeoutError
- **WHEN** Schwab returns HTTP 429
- **THEN** `ProviderTimeoutError` is raised (unchanged from existing behavior)
