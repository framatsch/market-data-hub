## 1. OAuth Endpoints

- [ ] 1.1 Create `app/api/routes_schwab.py` with endpoints for `authorize`, `callback`, and `paste`.
- [ ] 1.2 Update `app/main.py` or the appropriate router to include `routes_schwab.py`.

## 2. Credential Management

- [ ] 2.1 Ensure `schwab.token_json` is in the allowed credentials list for the `schwab` provider.
- [ ] 2.2 Use `KeyRepository` to store the OAuth tokens.

## 3. Schwab Provider Updates

- [ ] 3.1 Modify `app/providers/schwab.py` to check for token expiry in `_ensure_connection`.
- [ ] 3.2 Implement the refresh token flow using `httpx` to the Schwab token endpoint.
- [ ] 3.3 Update `schwab.token_json` in the `KeyRepository` when the token is refreshed.

## 4. Test Connection

- [ ] 4.1 Implement a test connection endpoint/method that fetches the account numbers using the valid access token.

## 5. Tests

- [ ] 5.1 Add unit tests for the OAuth flow (authorization URL generation, callback parsing).
- [ ] 5.2 Add tests for token refresh logic in `schwab.py`.
