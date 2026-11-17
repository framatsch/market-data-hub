## ADDED Requirements

### Requirement: Earnings caching
`GET /earnings/calendar`, `GET /earnings/next` and `GET /companies/{symbol}/earnings` SHALL be cached for JSON and CSV with the earnings TTL (default 21600 s = 6 h). Their key route segments SHALL be `earnings:calendar`, `earnings:next` and `companies:earnings`. The `symbols` parameter SHALL be normalised in the key (upper case, de-duplicated, sorted); `from` and `to` SHALL be day-granular. `GET /earnings/next` SHALL return its rows in the request order also on a cache hit. The market-closed extension SHALL NOT apply. Responses with `meta.stale = true` SHALL NOT be cached.

#### Scenario: Symbol order does not split the cache
- **WHEN** `GET /earnings/next?symbols=MSFT,AAPL` and then `GET /earnings/next?symbols=AAPL,MSFT` are requested within 6 h
- **THEN** the second request is a cache hit and its rows are in the order AAPL, MSFT

#### Scenario: Earnings key does not collide with the profile
- **WHEN** the admin clears scope `company_profile`
- **THEN** cached company earnings entries are not deleted

## MODIFIED Requirements

### Requirement: Runtime-configurable cache policy
The cache policy SHALL be adjustable at runtime via the Admin API/UI without restart and SHALL be persisted in `system_settings`. The stored keys are `cache_ttl_option_chain_seconds`, `cache_ttl_historical_closed_seconds`, `cache_ttl_historical_open_bar_seconds`, `cache_ttl_historical_intraday_seconds`, `cache_ttl_company_profile_seconds`, `cache_ttl_company_search_seconds`, `cache_ttl_company_news_seconds`, `cache_ttl_market_status_seconds`, `cache_ttl_volatility_seconds`, `cache_ttl_earnings_seconds` and `cache_extend_when_market_closed`. Environment values serve as defaults when no stored value exists. TTLs SHALL be integers from 0 to 2592000 (30 days). `0` disables caching for that policy, including its market-closed extension. Changes SHALL apply to entries written after the change; existing entries keep their remaining lifetime. Each replica SHALL pick up stored changes within 30 s. The same policy SHALL govern HTTP and MCP entries.

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

#### Scenario: Earnings TTL zero
- **WHEN** the earnings TTL is set to 0
- **THEN** earnings calendar, next-earnings and company-earnings responses and the earnings MCP tools are not written to Redis

### Requirement: Admin cache status endpoint
`GET /api/admin/cache` SHALL require admin authentication and return the cache state (`disabled` | `connected` | `unavailable`), the redacted Redis URL (no password), the effective cache policy (with its env defaults), the current market state (`session` | `settle_grace` | `settled`) with the next open timestamp, Redis memory usage (`used_memory`, `maxmemory`), and the number of keys per cached endpoint group (`options_chain`, `historical_prices`, `company_profile`, `company_search`, `company_news`, `market_status`, `volatility`, `earnings`, each including MCP entries) counted via non-blocking `SCAN`.

#### Scenario: Status with Redis connected
- **WHEN** an admin requests `GET /api/admin/cache` and Redis is reachable
- **THEN** the response contains `state: "connected"` and key counts for all eight cached endpoint groups

#### Scenario: Status without Redis
- **WHEN** Redis is unreachable
- **THEN** the response contains `state: "unavailable"` and HTTP 200 with null key counts

#### Scenario: Unauthenticated
- **WHEN** the request has no valid admin token
- **THEN** the API responds with 401


### Requirement: Admin cache clear endpoint
`POST /api/admin/cache/clear` SHALL require admin authentication and a body with `confirm: true`. It SHALL accept an optional `scope` (`all` default, `options_chain`, `historical_prices`, `company_profile`, `company_search`, `company_news`, `market_status`, `volatility` or `earnings`) and an optional `provider` filter. Each scope SHALL match both HTTP and MCP entries of its endpoints. The `volatility` scope SHALL match `mdh:volatility:*`, covering snapshot, history and stats. The `earnings` scope SHALL match `mdh:earnings:*` (including the provider calendar entries) and `mdh:companies:earnings:*`. It SHALL delete only matching `mdh:*` keys using `SCAN` + `UNLINK` (never `KEYS`/`FLUSHDB`), return the number of deleted keys, and write an audit log entry with the admin principal, scope, provider and count.

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

#### Scenario: Clear earnings
- **WHEN** an admin posts `{"confirm": true, "scope": "earnings"}`
- **THEN** only `mdh:earnings:*` and `mdh:companies:earnings:*` keys are removed, including MCP entries, and company profile entries stay

#### Scenario: Missing confirmation
- **WHEN** the body lacks `confirm: true`
- **THEN** the API responds with 400 and deletes nothing

#### Scenario: Redis unavailable
- **WHEN** Redis is unreachable or caching is disabled
- **THEN** the API responds with 503 and a descriptive message

#### Scenario: Foreign keys untouched
- **WHEN** the Redis database contains keys without the `mdh:` prefix
- **THEN** those keys are not deleted

