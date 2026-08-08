# Schwab OAuth Workflow

## Problem

Market Data Hub (MDH) needs to support fetching market data from Schwab. Schwab requires an OAuth2 flow with PKCE to obtain an access token and refresh token. TradeSensei already implements a Schwab OAuth workflow, but it stores credentials per account. MDH needs a similar workflow tailored to its architecture, where provider credentials (like the Schwab API key and OAuth tokens) are stored in the encrypted `keys.db` via the Admin UI/API rather than per user account.

## Solution

We will adapt the TradeSensei Schwab OAuth specification for MDH. We will implement:

1. **OAuth Authorization Start**: Generate a PKCE verifier and start the Schwab OAuth flow, redirecting the user to the Schwab login.
2. **OAuth Callback/Paste**: Handle the Schwab redirect (or let the admin paste the redirect URL) to exchange the code for an access and refresh token.
3. **Encrypted Storage**: Persist the obtained `schwab.token_json` (or similar) into MDH's `keys.db` utilizing the existing `KeyRepository`.
4. **Token Refresh**: Automatically refresh the Schwab access token using the refresh token before making broker API calls when the token is expired or expiring soon.

## Success Criteria

* Admin can initiate the Schwab OAuth connection.
* Admin can complete the connection via callback or paste mode.
* Schwab tokens are securely stored in the encrypted SQLite `keys.db`.
* MDH can transparently refresh the access token using the stored refresh token when making Schwab API requests.
