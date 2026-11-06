## ADDED Requirements

### Requirement: Company profile caching
`GET /companies/{symbol}` SHALL be cached with the company-profile TTL (default 86400 s = 24 h). The key route segment SHALL be `companies:profile`. The market-closed extension SHALL NOT apply.

#### Scenario: Repeated profile request
- **WHEN** `GET /companies/AAPL?provider=finnhub` is requested twice within 24 h
- **THEN** the provider is called once, the key is `mdh:companies:profile:AAPL:provider=finnhub`, and the second response carries `X-FastAPI-Cache: HIT`

#### Scenario: Profile key does not collide with sub-resources
- **WHEN** the admin clears scope `company_profile`
- **THEN** cached company search and company news entries are not deleted

### Requirement: Company search caching
`GET /companies/search` SHALL be cached with the company-search TTL (default 3600 s = 1 h). The key route segment SHALL be `companies:search`, the symbol segment SHALL be empty, and the `q` value SHALL be trimmed, whitespace-collapsed and lower-cased in the key. The market-closed extension SHALL NOT apply.

#### Scenario: Case-insensitive search key
- **WHEN** `GET /companies/search?q=Apple&provider=finnhub` and `GET /companies/search?q=%20apple%20&provider=finnhub` are requested
- **THEN** both use the key `mdh:companies:search::provider=finnhub&q=apple` and the provider is called once

#### Scenario: Empty result cached
- **WHEN** a search returns an empty list without error
- **THEN** the empty result is cached like any other successful response

### Requirement: Company news caching
`GET /companies/{symbol}/news` SHALL be cached for both JSON and CSV formats with the company-news TTL (default 600 s = 10 min). The key route segment SHALL be `companies:news`. The CSV variant SHALL be returned as a concrete `Response` (not a `StreamingResponse`) with unchanged body, media type and `Content-Disposition`. The market-closed extension SHALL NOT apply, because news is published outside trading hours.

#### Scenario: Repeated news request
- **WHEN** `GET /companies/AAPL/news?days=7` is requested twice within 10 minutes
- **THEN** the provider is called once and both responses have identical bodies including `meta`

#### Scenario: News CSV served from cache
- **WHEN** a `format=csv` news request is repeated
- **THEN** the cached response has the same body, `text/csv` media type and `Content-Disposition` header as the original

#### Scenario: Pagination isolated
- **WHEN** `offset=0` and `offset=20` are requested for the same symbol
- **THEN** they are stored under different keys

### Requirement: Market status caching
`GET /market-status` SHALL be cached with the market-status TTL (default 60 s). The key route segment SHALL be `market-status` with an empty symbol segment. The effective TTL SHALL be capped at the number of seconds until the next US session transition (weekdays 04:00, 09:30, 16:00 and 20:00 ET), so that a cached status never outlives a state change. The market-closed extension SHALL NOT apply.

#### Scenario: Normal status caching
- **WHEN** `GET /market-status?provider=polygon` is requested twice within 60 s at 11:00 ET on a weekday
- **THEN** the provider is called once and the key is `mdh:market-status::provider=polygon`

#### Scenario: Capped before the open
- **WHEN** the market status is requested at 09:29:30 ET on a weekday
- **THEN** the entry is cached for at most 30 s

### Requirement: MCP tool caching
The MCP tools `get_historical_prices`, `get_option_chain`, `get_company_profile`, `search_companies`, `get_company_news` and `get_market_status` SHALL be served through the same fail-open Redis backend and the same runtime TTL policy as their HTTP counterparts. Their keys SHALL use the HTTP route segment of the corresponding endpoint and the HTTP query parameter names, with the additional parameter `channel=mcp`, so that MCP entries are matched by the same clear scopes and provider filters but never shared with HTTP entries (the stored value shapes differ). Each cached tool SHALL accept an optional boolean `refresh` argument; `refresh: true` SHALL fetch live and overwrite the entry. The tools `get_last_price` and `get_option_quote` SHALL NOT be cached. Errors SHALL NOT be cached and caching SHALL be disabled when the HTTP cache is disabled.

#### Scenario: Agent repeats an option chain call
- **WHEN** an MCP client calls `get_option_chain` with `{"symbol": "SPX", "provider": "schwab"}` twice within the option-chain TTL during the session
- **THEN** the provider is called once and the key is `mdh:options:chain:SPX:channel=mcp&provider=schwab`

#### Scenario: Default provider resolved for MCP
- **WHEN** the default options provider is `schwab` and `get_option_chain` is called without `provider`
- **THEN** the key contains `provider=schwab`

#### Scenario: MCP forced refresh
- **WHEN** `get_company_profile` is called with `refresh: true`
- **THEN** the provider is called and the cache entry is overwritten

#### Scenario: Redis down during MCP call
- **WHEN** Redis is unreachable and an MCP tool is called
- **THEN** the tool returns live provider data without error

#### Scenario: HTTP client cannot read MCP entries
- **WHEN** `GET /options/SPX/chain?provider=schwab&channel=mcp` is requested via HTTP
- **THEN** `channel` is ignored as an undeclared parameter and the HTTP key `mdh:options:chain:SPX:provider=schwab` is used

### Requirement: Never-cached endpoints
The following SHALL NOT be cached and SHALL NOT carry a cache-derived `Cache-Control` header: `GET /prices/{symbol}/last`, `GET /options/{symbol}/quote/{option_id}`, `GET /health`, `GET /metrics`, `GET /providers`, every `/api/admin/*` route, every WebSocket route and the MCP tools `get_last_price` and `get_option_quote`. Live quotes require current data; health, metrics, provider and admin data reflect local state that must be immediately consistent.

#### Scenario: Last price is live
- **WHEN** `GET /prices/AAPL/last` is requested twice in a row
- **THEN** the provider is called twice and no `X-FastAPI-Cache` header is present

#### Scenario: Providers list reflects admin changes
- **WHEN** the default provider is changed in the Admin UI
- **THEN** the next `GET /providers` immediately shows the new default

## MODIFIED Requirements

### Requirement: Redis cache configuration
The system SHALL read cache configuration from Pydantic `BaseSettings` (environment / `.env`): `CACHE_ENABLED` (bool, default `true`), `REDIS_URL` (default `redis://localhost:6379/0`), `REDIS_TIMEOUT_SECONDS` (default `1.0`), and the initial cache policy `CACHE_TTL_OPTION_CHAIN_SECONDS` (default `900`), `CACHE_TTL_HISTORICAL_CLOSED_SECONDS` (default `604800`), `CACHE_TTL_HISTORICAL_OPEN_BAR_SECONDS` (default `300`), `CACHE_TTL_HISTORICAL_INTRADAY_SECONDS` (default `300`), `CACHE_TTL_COMPANY_PROFILE_SECONDS` (default `86400`), `CACHE_TTL_COMPANY_SEARCH_SECONDS` (default `3600`), `CACHE_TTL_COMPANY_NEWS_SECONDS` (default `600`), `CACHE_TTL_MARKET_STATUS_SECONDS` (default `60`) and `CACHE_EXTEND_WHEN_MARKET_CLOSED` (default `true`).

#### Scenario: Redis URL from environment
- **WHEN** `.env` contains `REDIS_URL=redis://cache:6379/2`
- **THEN** the cache backend connects to `redis://cache:6379/2`

#### Scenario: Caching disabled
- **WHEN** `CACHE_ENABLED=false`
- **THEN** no Redis connection is opened and every request and MCP tool call is served live from the provider without cache headers

#### Scenario: New TTL from environment
- **WHEN** `.env` contains `CACHE_TTL_COMPANY_PROFILE_SECONDS=3600` and no value is stored in `system_settings`
- **THEN** company profile entries expire after 3600 s

### Requirement: Transparent cache key naming
Cache keys SHALL follow `mdh:{route_path}:{symbol}:{query_params}` where `route_path` is the route template without path parameters joined by `:` unless the route declares an explicit route key (`companies:profile` for `GET /companies/{symbol}`), `symbol` is the upper-cased path symbol (empty when the route has none), and `query_params` is the URL-encoded, alphabetically sorted list of declared, non-empty query parameters (`-` when none). `provider`, `format` and `sec_type` values SHALL be lower-cased to mirror route normalization; the company search `q` value SHALL be trimmed, whitespace-collapsed and lower-cased. Undeclared query parameters SHALL NOT influence the key.

#### Scenario: Option chain key
- **WHEN** `GET /options/spx/chain?provider=Schwab` is requested
- **THEN** the cache key is `mdh:options:chain:SPX:provider=schwab`

#### Scenario: Explicit route key
- **WHEN** `GET /companies/aapl?provider=finnhub` is requested
- **THEN** the cache key is `mdh:companies:profile:AAPL:provider=finnhub`

#### Scenario: Route without symbol
- **WHEN** `GET /market-status?provider=polygon` is requested
- **THEN** the cache key is `mdh:market-status::provider=polygon`

### Requirement: Caching applies to all providers with provider-isolated keys
Caching SHALL apply regardless of the provider serving the request. The key SHALL always contain the effective provider: the explicit `provider` query parameter, or, when absent, the current system default for the endpoint's capability (`default_options_provider` for options, `default_price_provider` for prices and market status, `default_company_provider` for company profile and search, `default_news_provider` for company news).

#### Scenario: Implicit default provider
- **WHEN** the default options provider is `schwab` and `GET /options/SPX/chain` is requested
- **THEN** the cache key is `mdh:options:chain:SPX:provider=schwab`

#### Scenario: Implicit news provider
- **WHEN** the default news provider is `finnhub` and `GET /companies/AAPL/news` is requested
- **THEN** the cache key is `mdh:companies:news:AAPL:provider=finnhub`

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
The cache policy SHALL be adjustable at runtime via the Admin API/UI without restart and SHALL be persisted in `system_settings`. The stored keys are `cache_ttl_option_chain_seconds`, `cache_ttl_historical_closed_seconds`, `cache_ttl_historical_open_bar_seconds`, `cache_ttl_historical_intraday_seconds`, `cache_ttl_company_profile_seconds`, `cache_ttl_company_search_seconds`, `cache_ttl_company_news_seconds`, `cache_ttl_market_status_seconds` and `cache_extend_when_market_closed`. Environment values serve as defaults when no stored value exists. TTLs SHALL be integers from 0 to 2592000 (30 days). `0` disables caching for that policy, including its market-closed extension. Changes SHALL apply to entries written after the change; existing entries keep their remaining lifetime. Each replica SHALL pick up stored changes within 30 s. The same policy SHALL govern HTTP and MCP entries.

#### Scenario: Change TTL in Admin UI
- **WHEN** an admin sets the option-chain TTL to 300 s
- **THEN** new option-chain entries written during the session expire after 300 s, without restarting the application

#### Scenario: TTL zero disables a policy
- **WHEN** the intraday TTL is set to 0
- **THEN** open-range intraday history responses are served live and not written to Redis, at any time of day

#### Scenario: News TTL zero
- **WHEN** the company-news TTL is set to 0
- **THEN** HTTP news requests and the MCP `get_company_news` tool are served live and nothing is written to Redis

#### Scenario: Invalid TTL
- **WHEN** an admin submits a negative TTL or one above 2592000
- **THEN** the API responds with 422 and stored values are unchanged

#### Scenario: Env default
- **WHEN** no value is stored in `system_settings`
- **THEN** the corresponding `CACHE_*` environment value is used

### Requirement: Admin cache status endpoint
`GET /api/admin/cache` SHALL require admin authentication and return the cache state (`disabled` | `connected` | `unavailable`), the redacted Redis URL (no password), the effective cache policy (with its env defaults), the current market state (`session` | `settle_grace` | `settled`) with the next open timestamp, Redis memory usage (`used_memory`, `maxmemory`), and the number of keys per cached endpoint (`options_chain`, `historical_prices`, `company_profile`, `company_search`, `company_news`, `market_status`, each including MCP entries) counted via non-blocking `SCAN`.

#### Scenario: Status with Redis connected
- **WHEN** an admin requests `GET /api/admin/cache` and Redis is reachable
- **THEN** the response contains `state: "connected"` and key counts for all six cached endpoints

#### Scenario: Status without Redis
- **WHEN** Redis is unreachable
- **THEN** the response contains `state: "unavailable"` and HTTP 200 with null key counts

#### Scenario: Unauthenticated
- **WHEN** the request has no valid admin token
- **THEN** the API responds with 401

### Requirement: Admin cache clear endpoint
`POST /api/admin/cache/clear` SHALL require admin authentication and a body with `confirm: true`. It SHALL accept an optional `scope` (`all` default, `options_chain`, `historical_prices`, `company_profile`, `company_search`, `company_news`, `market_status`) and an optional `provider` filter. Each scope SHALL match both HTTP and MCP entries of its endpoint. It SHALL delete only matching `mdh:*` keys using `SCAN` + `UNLINK` (never `KEYS`/`FLUSHDB`), return the number of deleted keys, and write an audit log entry with the admin principal, scope, provider and count.

#### Scenario: Clear everything
- **WHEN** an admin posts `{"confirm": true}`
- **THEN** all `mdh:*` keys are removed and `deleted` reports the count

#### Scenario: Clear one provider's option chains
- **WHEN** an admin posts `{"confirm": true, "scope": "options_chain", "provider": "schwab"}`
- **THEN** only `mdh:options:chain:*` keys whose provider is `schwab` are removed, including MCP entries

#### Scenario: Clear company news
- **WHEN** an admin posts `{"confirm": true, "scope": "company_news"}`
- **THEN** only `mdh:companies:news:*` keys are removed

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
`PUT /api/admin/cache/policy` SHALL require admin authentication and accept any subset of `option_chain_seconds`, `historical_closed_seconds`, `historical_open_bar_seconds`, `historical_intraday_seconds`, `company_profile_seconds`, `company_search_seconds`, `company_news_seconds`, `market_status_seconds` (0–2592000) and `extend_when_market_closed` (bool). It SHALL persist the values in `system_settings`, apply them immediately on the handling replica, write an audit log entry, and return the effective policy. The endpoint SHALL work even when Redis is unavailable.

#### Scenario: Partial update
- **WHEN** an admin sends `{"historical_intraday_seconds": 120}`
- **THEN** only the intraday TTL changes and the response lists the full effective policy

#### Scenario: Update a new policy field
- **WHEN** an admin sends `{"company_news_seconds": 300}`
- **THEN** new news entries expire after 300 s and the response lists all nine policy fields

#### Scenario: Toggle extension
- **WHEN** an admin sends `{"extend_when_market_closed": false}`
- **THEN** subsequent writes outside the session use the session TTLs

### Requirement: Admin UI cache management
The Settings page SHALL show a "Response Cache" card with state, Redis URL, memory usage and key counts for all six cached endpoints. It SHALL show the current market state (session / settle grace / settled until next open). It SHALL include an editable policy form: option chain, closed ranges, open bar (daily+), intraday, company profile, company search, company news and market status, each with human-readable hints (e.g. "= 5 min", "= 7 d"), and a switch "Keep entries until next market open while the market is closed" with a note that the session model is US (09:30–16:00 ET), that it applies only to option chains and historical prices, and that it should be disabled for non-US symbols. The form SHALL note that changes apply to new entries only and SHALL have a Save button. The card SHALL also have a danger-zone "Clear cache…" button. The button SHALL open a confirmation dialog containing a warning that all following requests hit the broker APIs live (rate-limit risk), scope selector (all seven scopes) and provider selector, and an acknowledgement checkbox. The destructive "Clear cache" button SHALL stay disabled until the checkbox is ticked.

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
