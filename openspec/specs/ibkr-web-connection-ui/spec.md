# ibkr-web-connection-ui Specification

## Purpose
Admin UI section and admin endpoints for the `ibkrweb` gateway connection settings and the Client Portal Gateway session (status, initialise, logout, browser login).
## Requirements
### Requirement: IBKR Web connection section
The Connection / Auth tab of `ibkrweb` SHALL render an `IbkrWebConnectionSection` with inputs for all fields of `CONNECTION_CONFIG_ALLOWLIST["ibkrweb"]`: `base_url` (text), `verify_tls` (switch), `ca_bundle` (text, optional), `account_id` (text, optional), `compete` (switch, with the warning "Disconnects other IBKR sessions of this username (TWS, IB Gateway, IBKR Mobile)"), `market_data_type` (select `1=Live`, `2=Frozen`, `3=Delayed`, `4=Delayed Frozen`), `max_streams` (number) and `login_url` (text, optional, "Browser login URL"). "Open gateway login" SHALL open `login_url` when set, else `base_url`. Fields SHALL be pre-filled from `GET /api/admin/providers/ibkrweb/config` → `connection_config`, else with the defaults `https://127.0.0.1:5000`, `false`, empty, empty, `false`, `3`, `80`. "Save" SHALL call `PUT /api/admin/providers/ibkrweb/gateway`. The Connection Config JSON textarea SHALL be hidden for `ibkrweb` as it is for `ibkr`.

#### Scenario: Defaults shown
- **WHEN** the Connection / Auth tab opens for `ibkrweb` without saved `connection_config`
- **THEN** the fields show the defaults and the JSON textarea of the Configuration tab is not rendered

#### Scenario: Save
- **WHEN** the admin changes `base_url` and clicks "Save"
- **THEN** `PUT /api/admin/providers/ibkrweb/gateway` is called, the provider is reloaded and the snackbar "IBKR Web API gateway connection updated" is shown

#### Scenario: Invalid TLS setting
- **WHEN** the backend rejects the save with 422 for `verify_tls`
- **THEN** the form shows the error at the `verify_tls` field and keeps the input

### Requirement: Gateway update endpoint
`PUT /api/admin/providers/ibkrweb/gateway` SHALL accept a partial `IbkrWebGatewayUpdate` (`base_url`, `verify_tls`, `ca_bundle`, `account_id`, `compete`, `market_data_type` 1–4, `max_streams` 1–100, `login_url`), merge it into `connection_config`, validate the TLS rule of the provider spec, persist it and reload the registry. Unspecified fields SHALL remain unchanged.

#### Scenario: Partial update
- **WHEN** the endpoint is called with `{"compete": true}`
- **THEN** only `compete` changes in `connection_config`

### Requirement: Session status panel and actions
The section SHALL show a session panel fed by `GET /api/admin/providers/ibkrweb/session`, refreshed every 10 seconds while visible, with: state (`unreachable`, `login_required`, `competing`, `brokerage_pending`, `ready`, `rate_limited`), `connected`, `authenticated`, `competing`, live or paper (from `/sso/validate` `LOGIN_TYPE`, at most once per minute), username, server version, time until session expiry (`ssoExpires`), time of the last tickle, the remaining penalty pause and the last error. The endpoint SHALL answer from the provider's state without additional upstream requests except the rate-limited `/sso/validate`. Actions:

- "Open gateway login" SHALL open `base_url` in a new browser tab, with the note that the login must happen in a browser that reaches the gateway directly (same host or SSH tunnel).
- "Initialise brokerage session" SHALL call `POST /api/admin/providers/ibkrweb/session/init`, which runs the brokerage initialisation of the provider once and returns the new state.
- "Logout" SHALL ask for confirmation and call `POST /api/admin/providers/ibkrweb/session/logout`, which sends `POST /logout` to the gateway and sets the state to `login_required`.
- "Test connection" SHALL call `POST /api/admin/test-connection/ibkrweb` and show the result inline.

When `ibkrweb` is disabled, `GET .../session` SHALL return state `disabled` and the actions SHALL be disabled.

#### Scenario: Login required shown
- **WHEN** the provider state is `login_required`
- **THEN** the panel shows a warning "Login required at the Client Portal Gateway" with the "Open gateway login" button highlighted

#### Scenario: Ready session
- **WHEN** the state is `ready`
- **THEN** the panel shows `authenticated: true`, live or paper, the username and the time until expiry

#### Scenario: Manual initialisation
- **WHEN** the admin clicks "Initialise brokerage session" while the state is `brokerage_pending`
- **THEN** the endpoint runs `ssodh/init` once and the panel shows the resulting state

#### Scenario: Penalty pause shown
- **WHEN** the provider is in the 429 penalty pause
- **THEN** the panel shows state `rate_limited` and the remaining seconds

### Requirement: Single-session warning
When `ibkr` and `ibkrweb` are both enabled, the provider overview and both IBKR connection sections SHALL show the warning "IBKR allows one brokerage session per username. Use a second IBKR username for one of the two providers." `GET /api/admin/providers` SHALL expose this as `warnings: ["ibkr_single_session"]` on both providers.

#### Scenario: Both IBKR providers enabled
- **WHEN** `ibkr` and `ibkrweb` are enabled
- **THEN** both provider entries carry `warnings: ["ibkr_single_session"]` and the UI shows the warning

#### Scenario: Only one IBKR provider
- **WHEN** only `ibkrweb` is enabled
- **THEN** no single-session warning is shown

### Requirement: Auth section routing for ibkrweb
`ProvidersPage` and `DashboardPage` SHALL render `IbkrWebConnectionSection` in the Connection / Auth tab when `provider.name === 'ibkrweb'` and SHALL label the provider "IBKR Web API (CPGW)". `ibkrweb` SHALL have no entry in `CREDENTIAL_ALLOWLIST`.

#### Scenario: Routing
- **WHEN** the Connection / Auth tab is opened for `ibkrweb`
- **THEN** `IbkrWebConnectionSection` is rendered and no API key fields are shown

