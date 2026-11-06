## Why

The Redis response cache (`response-caching`) currently covers only `GET /options/{symbol}/chain` and `GET /prices/{symbol}/history`. All other provider-backed read endpoints still hit the broker APIs on every request, and the MCP tools bypass the cache entirely because they call the services directly — an AI agent looping over symbols can exhaust Schwab/Finnhub/Polygon rate limits even though the HTTP layer is protected. This change completes the cache so that every slow-changing, provider-backed read is protected, regardless of whether it arrives via HTTP or MCP.

## What Changes

- Cache `GET /companies/{symbol}` (company profile, default TTL 24 h).
- Cache `GET /companies/search` (company search, default TTL 1 h).
- Cache `GET /companies/{symbol}/news` (company news, default TTL 10 min), JSON and CSV. The CSV variant switches from `StreamingResponse` to a concrete `Response` so it can be stored.
- Cache `GET /market-status` (default TTL 60 s), capped so that an entry never outlives the next session open/close transition.
- Cache the MCP tools `get_historical_prices`, `get_option_chain`, `get_company_profile`, `search_companies`, `get_company_news` and `get_market_status` through the same fail-open backend, the same TTL policy and the same key scheme (with a `channel=mcp` marker). The MCP tools gain an optional `refresh` argument for a forced live fetch.
- Extend the key builder: explicit route key names (`companies:profile` instead of the ambiguous bare `companies`), effective default provider per capability (company, news, price for market status), and normalized search queries.
- Extend the runtime cache policy with `company_profile_seconds`, `company_search_seconds`, `company_news_seconds` and `market_status_seconds` (env defaults, stored in `system_settings`, editable in the Admin API/UI).
- Extend admin cache status key counts and clear scopes with `company_profile`, `company_search`, `company_news` and `market_status`.
- Document explicitly which endpoints are **never** cached: `/prices/{symbol}/last`, `/options/{symbol}/quote/{option_id}`, `/health`, `/metrics`, `/providers`, `/api/admin/*`, WebSockets and the MCP tools `get_last_price` / `get_option_quote`.
- No breaking API changes. Existing keys for option chains and historical prices are unchanged.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `response-caching`: adds caching for company profile, search, news and market status; adds MCP tool caching; extends key naming (route key override, provider mapping per capability), configuration, runtime policy, admin status/clear scopes and the Admin UI card; defines the explicit never-cached list.

## Impact

- **Code**: `app/cache.py` (key builder, policy, scopes, new `cached_call` helper for non-HTTP callers), `app/config.py`, `app/admin/settings_repository.py` (allowlist), `app/api/routes_companies.py`, `app/api/routes_meta.py`, `app/api/mcp.py`, `app/api/routes_admin.py` (scope enum via `CacheScope`), `app/market_hours.py` (next session transition helper).
- **Admin UI**: `admin/src/components/CacheCard.tsx` (four new TTL fields, key counts, clear scopes) and its API types.
- **Config**: `.env.example` gains `CACHE_TTL_COMPANY_PROFILE_SECONDS`, `CACHE_TTL_COMPANY_SEARCH_SECONDS`, `CACHE_TTL_COMPANY_NEWS_SECONDS`, `CACHE_TTL_MARKET_STATUS_SECONDS`.
- **Dependencies**: none (uses existing `fastapi-cache2[redis]`).
- **Behavior**: up to TTL-old company data, news and market status for HTTP and MCP clients; clients/agents can force fresh data via `Cache-Control: no-cache` (HTTP) or `refresh: true` (MCP).
