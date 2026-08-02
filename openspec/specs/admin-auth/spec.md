# admin-auth Specification

## Purpose
TBD - created by archiving change admin-ui-backend. Update Purpose after archive.
## Requirements
### Requirement: Auth toggle via ADMIN_AUTH_ENABLED
The system SHALL support an `ADMIN_AUTH_ENABLED` boolean setting (default: `false`). When `false`, all `/api/admin/*` endpoints SHALL be accessible without any token. When `true`, all `/api/admin/*` endpoints SHALL require a valid Bearer JWT.

#### Scenario: Auth disabled — no token required
- **WHEN** `ADMIN_AUTH_ENABLED=false` and a request arrives at `/api/admin/providers` without `Authorization` header
- **THEN** the request proceeds and returns 200

#### Scenario: Auth enabled — missing token rejected
- **WHEN** `ADMIN_AUTH_ENABLED=true` and a request arrives at `/api/admin/providers` without `Authorization` header
- **THEN** the system returns HTTP 401 with `{"detail": "Not authenticated"}`

#### Scenario: Auth enabled — invalid token rejected
- **WHEN** `ADMIN_AUTH_ENABLED=true` and the Bearer token has an invalid signature
- **THEN** the system returns HTTP 401 with `{"detail": "Invalid token"}`

### Requirement: OIDC JWT validation via JWKS
When `ADMIN_AUTH_ENABLED=true`, the backend SHALL validate Bearer JWTs by fetching the JWKS from `{ADMIN_OIDC_ISSUER}/.well-known/jwks.json`. The JWKS SHALL be cached in-process and refreshed at most once per hour.

#### Scenario: Valid JWT accepted
- **WHEN** the Bearer token is signed by the OIDC provider's current key and not expired
- **THEN** the request proceeds to the handler

#### Scenario: JWKS cache refresh on validation failure
- **WHEN** JWT validation fails due to unknown key ID (`kid`)
- **THEN** the system immediately refreshes the JWKS cache and retries validation once before returning 401

### Requirement: PKCE authorization code flow
The backend SHALL expose `GET /api/admin/auth/url?code_challenge=<challenge>` to generate an OIDC authorization URL using the SPA-generated PKCE challenge (code_challenge_method=S256). It SHALL expose `POST /api/admin/auth/token` to exchange an authorization code plus SPA-held `code_verifier` for tokens, proxying to the OIDC provider's token endpoint.

#### Scenario: Authorization URL generated
- **WHEN** SPA generates a PKCE verifier/challenge pair and calls `GET /api/admin/auth/url?code_challenge=<challenge>`
- **THEN** response contains `{"auth_url": "https://authentik.../authorize?client_id=...&code_challenge=...&..."}`

#### Scenario: Token exchange succeeds
- **WHEN** SPA calls `POST /api/admin/auth/token` with `{"code": "...", "code_verifier": "..."}`
- **THEN** backend exchanges with OIDC provider and returns `{"access_token": "...", "expires_in": 3600}`

### Requirement: /api/admin/auth/me returns current principal
`GET /api/admin/auth/me` SHALL return the authenticated user's identity when auth is enabled, or `{"user": "local", "auth_enabled": false}` when disabled.

#### Scenario: Auth enabled — valid token
- **WHEN** `ADMIN_AUTH_ENABLED=true` and request has valid Bearer token
- **THEN** response is `{"user": "<subject claim>", "auth_enabled": true}`

#### Scenario: Auth disabled
- **WHEN** `ADMIN_AUTH_ENABLED=false`
- **THEN** response is `{"user": "local", "auth_enabled": false}` with status 200

