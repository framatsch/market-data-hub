## ADDED Requirements

### Requirement: Implied volatility caching
The endpoints `GET /volatility/{symbol}`, `GET /volatility/{symbol}/history` and `GET /volatility/{symbol}/stats` SHALL be cached for both JSON and CSV formats. Their key route segments SHALL be `volatility:snapshot`, `volatility:history` and `volatility:stats`.

The TTLs SHALL be:
- **Snapshot and stats**: the implied-volatility TTL (default 900 s).
- **History with a closed range**: an explicit `end` before yesterday 00:00 ET (the same closed-range rule as `1d` historical prices) SHALL use the closed-range TTL (default 604800 s = 7 days).
- **History with any other range**: the implied-volatility TTL.

The market-closed extension SHALL NOT apply to any volatility route, because daily IV values are published after the session close.

#### Scenario: Repeated snapshot request
- **WHEN** `GET /volatility/AAPL?provider=lseg` is requested twice within 15 minutes
- **THEN** the provider is called once, the key is `mdh:volatility:snapshot:AAPL:provider=lseg`, and the second response carries `X-FastAPI-Cache: HIT`

#### Scenario: Closed history range
- **WHEN** `GET /volatility/AAPL/history?start=2025-01-01&end=2025-12-31` is requested in November 2026
- **THEN** the entry is cached for the closed-range TTL (7 days)

#### Scenario: Open history range
- **WHEN** `GET /volatility/AAPL/history` without `end` is requested
- **THEN** the entry is cached for the implied-volatility TTL

#### Scenario: No extension overnight
- **WHEN** a volatility snapshot is requested Wednesday 16:35 ET with the market-closed extension enabled
- **THEN** the entry is cached for the implied-volatility TTL (900 s), not until the next open

#### Scenario: Stats keyed by window
- **WHEN** `GET /volatility/SPY/stats?sec_type=etf&window=252` and `GET /volatility/SPY/stats?sec_type=etf&window=126` are requested
- **THEN** they are stored under different keys

#### Scenario: Instrument override isolated
- **WHEN** `GET /volatility/DAX?ric=GDAXATMIV.EX` and `GET /volatility/DAX` are requested
- **THEN** they are stored under different keys because `ric` is part of the key

## MODIFIED Requirements

### Requirement: Redis cache configuration
The system SHALL read cache configuration from Pydantic `BaseSettings` (environment / `.env`):
- `CACHE_ENABLED` (bool, default `true`)
- `REDIS_URL` (default `redis://localhost:6379/0`)
- `REDIS_TIMEOUT_SECONDS` (default `1.0`)

It SHALL also read the initial cache policy:

| Setting | Default |
|---|---|
| `CACHE_TTL_OPTION_CHAIN_SECONDS` | `900` |
| `CACHE_TTL_HISTORICAL_CLOSED_SECONDS` | `604800` |
| `CACHE_TTL_HISTORICAL_OPEN_BAR_SECONDS` | `300` |
| `CACHE_TTL_HISTORICAL_INTRADAY_SECONDS` | `300` |
| `CACHE_TTL_COMPANY_PROFILE_SECONDS` | `86400` |
| `CACHE_TTL_COMPANY_SEARCH_SECONDS` | `3600` |
| `CACHE_TTL_COMPANY_NEWS_SECONDS` | `600` |
| `CACHE_TTL_MARKET_STATUS_SECONDS` | `60` |
| `CACHE_TTL_VOLATILITY_SECONDS` | `900` |
| `CACHE_EXTEND_WHEN_MARKET_CLOSED` | `true` |

#### Scenario: Redis URL from environment
- **WHEN** `.env` contains `REDIS_URL=redis://cache:6379/2`
- **THEN** the cache backend connects to `redis://cache:6379/2`

#### Scenario: Caching disabled
- **WHEN** `CACHE_ENABLED=false`
- **THEN** no Redis connection is opened and every request and MCP tool call is served live from the provider without cache headers

#### Scenario: New TTL from environment
- **WHEN** `.env` contains `CACHE_TTL_COMPANY_PROFILE_SECONDS=3600` and no value is stored in `system_settings`
- **THEN** company profile entries expire after 3600 s

#### Scenario: Volatility TTL from environment
- **WHEN** `.env` contains `CACHE_TTL_VOLATILITY_SECONDS=3600` and no value is stored in `system_settings`
- **THEN** volatility snapshot entries expire after 3600 s

### Requirement: Caching applies to all providers with provider-isolated keys
Caching SHALL apply regardless of the provider serving the request. The key SHALL always contain the effective provider. That is the explicit `provider` query parameter or, when absent, the current system default for the endpoint's capability:

| Endpoints | Default setting |
|---|---|
| options | `default_options_provider` |
| prices, market status | `default_price_provider` |
| company profile, company search | `default_company_provider` |
| company news | `default_news_provider` |
| volatility snapshot, history, stats | `default_volatility_provider` |

#### Scenario: Implicit default provider
- **WHEN** the default options provider is `schwab` and `GET /options/SPX/chain` is requested
- **THEN** the cache key is `mdh:options:chain:SPX:provider=schwab`

#### Scenario: Implicit news provider
- **WHEN** the default news provider is `finnhub` and `GET /companies/AAPL/news` is requested
- **THEN** the cache key is `mdh:companies:news:AAPL:provider=finnhub`

#### Scenario: Implicit volatility provider
- **WHEN** the default volatility provider is `lseg` and `GET /volatility/AAPL` is requested
- **THEN** the cache key is `mdh:volatility:snapshot:AAPL:provider=lseg`

#### Scenario: Explicit and implicit provider share an entry
- **WHEN** the default options provider is `schwab` and `GET /options/SPX/chain` and `GET /options/SPX/chain?provider=schwab` are requested
- **THEN** both requests use the same cache entry

#### Scenario: Default provider changed
- **WHEN** the default options provider changes from `schwab` to `ibkr` in the Admin UI
- **THEN** a subsequent `GET /options/SPX/chain` uses the key `mdh:options:chain:SPX:provider=ibkr` and never returns Schwab data

#### Scenario: No provider configured
- **WHEN** no default provider is configured and no `provider` is given
- **THEN** the request fails with `PROVIDER_NOT_AVAILABLE` and nothing is cached

#### Scenario: Parameter order independence
- **WHEN** `GET /prices/AAPL/history?provider=schwab&interval=1d` and `GET /prices/AAPL/history?interval=1d&provider=schwab` are requested
- **THEN** both resolve to `mdh:prices:history:AAPL:interval=1d&provider=schwab`

#### Scenario: No query parameters
- **WHEN** a cached route without a provider capability mapping is requested without query parameters
- **THEN** the query segment of the key is `-`

#### Scenario: Unknown parameters ignored
- **WHEN** `GET /options/SPX/chain?provider=schwab&_ts=123` is requested
- **THEN** the cache key is `mdh:options:chain:SPX:provider=schwab`

### Requirement: Runtime-configurable cache policy
The cache policy SHALL be adjustable at runtime via the Admin API/UI without restart and SHALL be persisted in `system_settings`. The stored keys are:
- `cache_ttl_option_chain_seconds`
- `cache_ttl_historical_closed_seconds`
- `cache_ttl_historical_open_bar_seconds`
- `cache_ttl_historical_intraday_seconds`
- `cache_ttl_company_profile_seconds`
- `cache_ttl_company_search_seconds`
- `cache_ttl_company_news_seconds`
- `cache_ttl_market_status_seconds`
- `cache_ttl_volatility_seconds`
- `cache_extend_when_market_closed`

Further rules:
- Environment values serve as defaults when no stored value exists.
- TTLs SHALL be integers from 0 to 2592000 (30 days). `0` disables caching for that policy, including its market-closed extension.
- Changes SHALL apply to entries written after the change; existing entries keep their remaining lifetime.
- Each replica SHALL pick up stored changes within 30 s.
- The same policy SHALL govern HTTP and MCP entries.

#### Scenario: Change TTL in Admin UI
- **WHEN** an admin sets the option-chain TTL to 300 s
- **THEN** new option-chain entries written during the session expire after 300 s, without restarting the application

#### Scenario: TTL zero disables a policy
- **WHEN** the intraday TTL is set to 0
- **THEN** open-range intraday history responses are served live and not written to Redis, at any time of day

#### Scenario: News TTL zero
- **WHEN** the company-news TTL is set to 0
- **THEN** HTTP news requests and the MCP `get_company_news` tool are served live and nothing is written to Redis

#### Scenario: Volatility TTL zero
- **WHEN** the implied-volatility TTL is set to 0
- **THEN** volatility snapshots, stats and open-range volatility history are served live, while closed-range volatility history still uses the closed-range TTL

#### Scenario: Invalid TTL
- **WHEN** an admin submits a negative TTL or one above 2592000
- **THEN** the API responds with 422 and stored values are unchanged

#### Scenario: Env default
- **WHEN** no value is stored in `system_settings`
- **THEN** the corresponding `CACHE_*` environment value is used

### Requirement: Admin cache status endpoint
`GET /api/admin/cache` SHALL require admin authentication. It SHALL return:
- the cache state (`disabled` | `connected` | `unavailable`)
- the redacted Redis URL (no password)
- the effective cache policy, with its env defaults
- the current market state (`session` | `settle_grace` | `settled`) with the next open timestamp
- Redis memory usage (`used_memory`, `maxmemory`)
- the number of keys per cached endpoint group, each including MCP entries and counted via non-blocking `SCAN`: `options_chain`, `historical_prices`, `company_profile`, `company_search`, `company_news`, `market_status`, `volatility`

#### Scenario: Status with Redis connected
- **WHEN** an admin requests `GET /api/admin/cache` and Redis is reachable
- **THEN** the response contains `state: "connected"` and key counts for all seven cached endpoint groups

#### Scenario: Status without Redis
- **WHEN** Redis is unreachable
- **THEN** the response contains `state: "unavailable"` and HTTP 200 with null key counts

#### Scenario: Unauthenticated
- **WHEN** the request has no valid admin token
- **THEN** the API responds with 401

### Requirement: Admin cache clear endpoint
`POST /api/admin/cache/clear` SHALL require admin authentication and a body with `confirm: true`. It SHALL accept:
- an optional `scope`: `all` (default), `options_chain`, `historical_prices`, `company_profile`, `company_search`, `company_news`, `market_status` or `volatility`
- an optional `provider` filter

Each scope SHALL match both HTTP and MCP entries of its endpoints. The `volatility` scope SHALL match `mdh:volatility:*`, covering snapshot, history and stats.

The endpoint SHALL delete only matching `mdh:*` keys using `SCAN` + `UNLINK` (never `KEYS`/`FLUSHDB`) and return the number of deleted keys. It SHALL write an audit log entry with the admin principal, scope, provider and count.

#### Scenario: Clear everything
- **WHEN** an admin posts `{"confirm": true}`
- **THEN** all `mdh:*` keys are removed and `deleted` reports the count

#### Scenario: Clear one provider's option chains
- **WHEN** an admin posts `{"confirm": true, "scope": "options_chain", "provider": "schwab"}`
- **THEN** only `mdh:options:chain:*` keys whose provider is `schwab` are removed, including MCP entries

#### Scenario: Clear company news
- **WHEN** an admin posts `{"confirm": true, "scope": "company_news"}`
- **THEN** only `mdh:companies:news:*` keys are removed

#### Scenario: Clear implied volatility
- **WHEN** an admin posts `{"confirm": true, "scope": "volatility", "provider": "lseg"}`
- **THEN** only `mdh:volatility:*` keys whose provider is `lseg` are removed, including MCP entries

#### Scenario: Missing confirmation
- **WHEN** the body lacks `confirm: true`
- **THEN** the API responds with 400 and deletes nothing

#### Scenario: Redis unavailable
- **WHEN** Redis is unreachable or caching is disabled
- **THEN** the API responds with 503 and a descriptive message

#### Scenario: Foreign keys untouched
- **WHEN** the Redis database contains keys without the `mdh:` prefix
- **THEN** those keys are not deleted

### Requirement: Admin cache policy update endpoint
`PUT /api/admin/cache/policy` SHALL require admin authentication. It SHALL accept any subset of these fields:
- TTLs (0–2592000): `option_chain_seconds`, `historical_closed_seconds`, `historical_open_bar_seconds`, `historical_intraday_seconds`, `company_profile_seconds`, `company_search_seconds`, `company_news_seconds`, `market_status_seconds`, `volatility_seconds`
- `extend_when_market_closed` (bool)

It SHALL persist the values in `system_settings`, apply them immediately on the handling replica, write an audit log entry and return the effective policy. The endpoint SHALL work even when Redis is unavailable.

#### Scenario: Partial update
- **WHEN** an admin sends `{"historical_intraday_seconds": 120}`
- **THEN** only the intraday TTL changes and the response lists the full effective policy

#### Scenario: Update a new policy field
- **WHEN** an admin sends `{"volatility_seconds": 3600}`
- **THEN** new volatility snapshot entries expire after 3600 s and the response lists all ten policy fields

#### Scenario: Toggle extension
- **WHEN** an admin sends `{"extend_when_market_closed": false}`
- **THEN** subsequent writes outside the session use the session TTLs

### Requirement: Admin UI cache management
The Settings page SHALL show a "Response Cache" card with the following content.

**Status:**
- State, Redis URL, memory usage and key counts for all seven cached endpoint groups.
- The current market state (session / settle grace / settled until next open).

**Policy form:**
- Editable TTL fields: option chain, closed ranges, open bar (daily+), intraday, company profile, company search, company news, market status and implied volatility. Each field SHALL show a human-readable hint (e.g. "= 5 min", "= 7 d").
- A switch "Keep entries until next market open while the market is closed". Its note SHALL say that the session model is US (09:30–16:00 ET), that it applies only to option chains and historical prices (not to implied volatility), and that it should be disabled for non-US symbols.
- A note that changes apply to new entries only, and a Save button.

**Clear cache (danger zone):**
- A "Clear cache…" button that opens a confirmation dialog.
- The dialog SHALL contain a warning that all following requests hit the broker APIs live (rate-limit risk), a scope selector (all eight scopes), a provider selector and an acknowledgement checkbox.
- The destructive "Clear cache" button SHALL stay disabled until the checkbox is ticked.

#### Scenario: Confirm via checkbox
- **WHEN** the admin opens the dialog, ticks the acknowledgement and clicks "Clear cache"
- **THEN** the clear endpoint is called with `confirm: true`, a success message shows the deleted count, and the status card refreshes

#### Scenario: Not acknowledged
- **WHEN** the checkbox is not ticked
- **THEN** the "Clear cache" button is disabled

#### Scenario: Cache not available
- **WHEN** the state is `disabled` or `unavailable`
- **THEN** the "Clear cache…" button is disabled and the card explains why

#### Scenario: Edit news TTL
- **WHEN** the admin sets "Company news" to 300 and clicks Save
- **THEN** the policy endpoint is called with `company_news_seconds: 300` and the hint shows "= 5 min"

#### Scenario: Edit implied volatility TTL
- **WHEN** the admin sets "Implied volatility" to 3600 and clicks Save
- **THEN** the policy endpoint is called with `volatility_seconds: 3600` and the hint shows "= 1 h"

### Requirement: MCP tool caching
The following MCP tools SHALL be served through the same fail-open Redis backend and the same runtime TTL policy as their HTTP counterparts: `get_historical_prices`, `get_option_chain`, `get_company_profile`, `search_companies`, `get_company_news`, `get_market_status`, `get_implied_volatility`, `get_implied_volatility_history` and `get_implied_volatility_stats`.

Key and behavior rules:
- Keys SHALL use the HTTP route segment and HTTP query parameter names of the corresponding endpoint, plus the parameter `channel=mcp`. MCP entries are therefore matched by the same clear scopes and provider filters, but never shared with HTTP entries (the stored value shapes differ).
- Each cached tool SHALL accept an optional boolean `refresh` argument. `refresh: true` SHALL fetch live and overwrite the entry.
- The tools `get_last_price` and `get_option_quote` SHALL NOT be cached.
- Errors SHALL NOT be cached, and caching SHALL be disabled when the HTTP cache is disabled.

#### Scenario: Agent repeats an option chain call
- **WHEN** an MCP client calls `get_option_chain` with `{"symbol": "SPX", "provider": "schwab"}` twice within the option-chain TTL during the session
- **THEN** the provider is called once and the key is `mdh:options:chain:SPX:channel=mcp&provider=schwab`

#### Scenario: Default provider resolved for MCP
- **WHEN** the default options provider is `schwab` and `get_option_chain` is called without `provider`
- **THEN** the key contains `provider=schwab`

#### Scenario: Agent repeats an IV stats call
- **WHEN** an MCP client calls `get_implied_volatility_stats` with `{"symbol": "SPY", "sec_type": "etf"}` twice within the implied-volatility TTL and the default volatility provider is `lseg`
- **THEN** the provider is called once and the key is `mdh:volatility:stats:SPY:channel=mcp&provider=lseg&sec_type=etf`

#### Scenario: MCP forced refresh
- **WHEN** `get_company_profile` is called with `refresh: true`
- **THEN** the provider is called and the cache entry is overwritten

#### Scenario: Redis down during MCP call
- **WHEN** Redis is unreachable and an MCP tool is called
- **THEN** the tool returns live provider data without error

#### Scenario: HTTP client cannot read MCP entries
- **WHEN** `GET /options/SPX/chain?provider=schwab&channel=mcp` is requested via HTTP
- **THEN** `channel` is ignored as an undeclared parameter and the HTTP key `mdh:options:chain:SPX:provider=schwab` is used
