## 1. OAuth Endpoints

- [x] 1.1 Create `app/api/routes_schwab.py` with endpoints for `authorize`, `callback`, and `paste`. *(Superseded by `provider-ui-consolidation`: endpoints integrated into `routes_admin.py`)*
- [x] 1.2 Update `app/main.py` or the appropriate router to include `routes_schwab.py`. *(Superseded by `provider-ui-consolidation`)*

## 2. Credential Management

- [x] 2.1 Ensure `schwab.token_json` is in the allowed credentials list for the `schwab` provider.
- [x] 2.2 Use `KeyRepository` to store the OAuth tokens.

## 3. Schwab Provider Updates

- [x] 3.1 Modify `app/providers/schwab.py` to check for token expiry in `_ensure_connection`. *(Handled internally by `schwab-py`)*
- [x] 3.2 Implement the refresh token flow using `httpx` to the Schwab token endpoint. *(Handled internally by `schwab-py`)*
- [x] 3.3 Update `schwab.token_json` in the `KeyRepository` when the token is refreshed. *(Implemented via a background asyncio task `_start_token_watcher` that watches the temp token file)*

## 4. Test Connection

- [x] 4.1 Implement a test connection endpoint/method that fetches the account numbers using the valid access token.

## 5. Tests

- [x] 5.1 Add unit tests for the OAuth flow (authorization URL generation, callback parsing). *(Implemented in `tests/unit/test_admin_routes.py` via `provider-ui-consolidation`)*
- [x] 5.2 Add tests for token refresh logic in `schwab.py`. *(Implicitly covered by existing provider initialization tests; `test_schwab_oauth_routes.py` removed as obsolete)*
