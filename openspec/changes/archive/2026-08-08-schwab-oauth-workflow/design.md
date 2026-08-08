# Design

## Architecture

We will implement the Schwab OAuth workflow using the existing FastAPI structure and Provider Registry in MDH.

1. **API Endpoints (`app/api/routes_schwab.py`)**:
   - `GET /api/admin/providers/schwab/oauth/authorize`: Initiates the flow, generates PKCE verifier, saves state, and returns the Schwab authorization URL.
   - `GET /api/admin/providers/schwab/oauth/callback`: Receives the redirect from Schwab with `code` and `state`, validates them, and exchanges the code for tokens.
   - `POST /api/admin/providers/schwab/oauth/paste`: Accepts a pasted redirect URL and exchanges the code for tokens.

2. **Credential Storage (`keys.db`)**:
   - The token data (access token, refresh token, expiry) will be stored as encrypted JSON under a new key, e.g., `schwab.token_json` (or separate `schwab.access_token`, `schwab.refresh_token`), in the `keys.db` SQLite database using `KeyRepository`.
   - The admin first needs to set `schwab.api_key` and `schwab.app_secret` in the encrypted store.

3. **Provider Implementation (`app/providers/schwab.py`)**:
   - Similar to the IBKR provider, the Schwab provider will implement the `_is_valid`, `_ensure_connection` methods.
   - The `_ensure_connection` method will check the expiry of the `schwab.token_json`. If it's expired or expiring soon, it will use the refresh token to obtain a new access token and persist the updated `schwab.token_json` via `KeyRepository`.

## Data Model Changes

- No new SQL tables are required, as `keys.db` and the existing `KeyRepository` can accommodate arbitrary keys per provider.
- We will add `schwab.token_json` to the allowed credentials list for the Schwab provider in the admin service config if not already present.
