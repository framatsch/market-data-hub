# schwab-paused-state Specification

## Purpose
TBD - created by archiving change admin-ui-backend. Update Purpose after archive.
## Requirements
### Requirement: _paused flag prevents error loop
`SchwabProvider` SHALL maintain a `_paused: bool` instance variable (default `False`). When `_paused` is `True`, calls to `_get_client()` SHALL raise `ProviderConnectionError` immediately without calling `easy_client()` or making any network request.

#### Scenario: Paused provider raises immediately
- **WHEN** `SchwabProvider._paused = True` and `get_last_price()` is called
- **THEN** `ProviderConnectionError` is raised immediately without any HTTP call to Schwab

#### Scenario: Unpaused provider operates normally
- **WHEN** `SchwabProvider._paused = False`
- **THEN** `_get_client()` proceeds with normal initialization logic

### Requirement: 401/403 on refresh sets paused and fires webhook
When `_handle_error_status` receives a 401 or 403 status AND `_client` was not `None` at the time of the error (indicating a refresh failure, not an initial auth failure), the provider SHALL set `_paused = True` and fire an async webhook notification to `SCHWAB_ALERT_WEBHOOK_URL` if configured. The webhook fire SHALL be a fire-and-forget background task (errors are logged, not raised).

#### Scenario: Refresh token expired — provider pauses
- **WHEN** an API call returns 401 after successful initialization (client was not None)
- **THEN** `_paused = True`, `_client = None`, `ProviderConnectionError` is raised

#### Scenario: Webhook fired on expiry
- **WHEN** `SCHWAB_ALERT_WEBHOOK_URL` is set and token expiry is detected
- **THEN** an HTTP POST is made to the webhook URL with `{"text": "Schwab token expired — re-authorization required via MDH Admin UI"}` as a background task

#### Scenario: Missing webhook URL — no error
- **WHEN** `SCHWAB_ALERT_WEBHOOK_URL` is empty
- **THEN** no webhook call is made and the provider continues without error

#### Scenario: Webhook failure does not affect provider behavior
- **WHEN** the webhook URL is unreachable
- **THEN** the error is logged at WARNING level and does not affect the `ProviderConnectionError` being raised

### Requirement: Paused state reset via auth callback
When `POST /api/admin/schwab/auth/callback` successfully completes re-authorization, the `SchwabProvider` singleton SHALL have `_paused = False` and `_client = None` set. Subsequent requests SHALL trigger normal re-initialization via `_get_client()`.

#### Scenario: Provider resumes after re-auth
- **WHEN** `POST /api/admin/schwab/auth/callback` succeeds
- **THEN** `SchwabProvider._paused = False` and the next price request succeeds by re-initializing the client

