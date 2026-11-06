## 1. Configuration & Policy

- [x] 1.1 Add `CACHE_TTL_COMPANY_PROFILE_SECONDS` (86400), `CACHE_TTL_COMPANY_SEARCH_SECONDS` (3600), `CACHE_TTL_COMPANY_NEWS_SECONDS` (600), `CACHE_TTL_MARKET_STATUS_SECONDS` (60) to `app/config.py` and document them in `.env.example`
- [x] 1.2 Add `company_profile_seconds`, `company_search_seconds`, `company_news_seconds`, `market_status_seconds` to `CachePolicyValues`, `CachePolicyUpdate` and `policy_defaults()` in `app/cache.py`
- [x] 1.3 Add the four `cache_ttl_*` keys to the settings-repository allowlist in `app/admin/settings_repository.py`
- [x] 1.4 Add `next_transition(now)` to `app/market_hours.py` (weekday 04:00/09:30/16:00/20:00 ET) with unit tests incl. weekend and DST

## 2. Key Builder & TTL Resolution

- [x] 2.1 Extract key composition into a shared `_compose_key(route_key, symbol, params)` used by `mdh_key_builder`; keep option-chain/history keys unchanged (regression test)
- [x] 2.2 Support an explicit route key in `cache(expire=..., key=...)` via the fastapi-cache2 namespace and use it in the key builder
- [x] 2.3 Map default providers per full route key (`options:chain`, `prices:history`, `market-status`, `companies:profile`, `companies:search`, `companies:news`)
- [x] 2.4 Normalize the search `q` value in the key (trim, collapse whitespace, lower-case)
- [x] 2.5 Extend `CachePolicy.resolve` with the new routes; restrict the market-closed extension to `options:chain` and `prices:history`; cap market status at `next_transition`
- [x] 2.6 Add scopes `company_profile`, `company_search`, `company_news`, `market_status` to `CacheScope` and `_PATTERNS`; count them in `cache_status()`

## 3. HTTP Endpoints

- [x] 3.1 Decorate `GET /companies/{symbol}` with `@cache(..., key="companies:profile")`
- [x] 3.2 Decorate `GET /companies/search`
- [x] 3.3 Decorate `GET /companies/{symbol}/news` and switch its CSV branch from `StreamingResponse` to `Response`
- [x] 3.4 Decorate `GET /market-status`
- [x] 3.5 Verify `response_model` routes still serialize correctly on HIT (decoded dict path)

## 4. MCP Tools

- [x] 4.1 Implement `cached_call(route_key, symbol, params, loader, *, refresh=False)` in `app/cache.py` (enable flag, fail-open backend, `channel=mcp`, no error caching)
- [x] 4.2 Wrap `get_historical_prices`, `get_option_chain`, `get_company_profile`, `search_companies`, `get_company_news`, `get_market_status` in `app/api/mcp.py` using HTTP parameter names (`start`, `end`, `expiry`, `from_date`, `to_date`, `limit`, …)
- [x] 4.3 Add the optional `refresh` boolean to the input schemas of the six cached tools in `TOOL_REGISTRY`; leave `get_last_price` and `get_option_quote` uncached

## 5. Admin UI

- [x] 5.1 Add the four TTL fields with duration hints to `admin/src/components/CacheCard.tsx` and the policy types
- [x] 5.2 Show key counts for all six endpoints and add the four new clear scopes to the dialog
- [x] 5.3 Update the extension switch note (applies to option chains and historical prices only)
- [x] 5.4 Run the admin build/lint and existing UI tests

## 6. Tests & Verification

- [x] 6.1 Route tests: HIT/MISS, identical body, provider called once for profile, search, news (JSON + CSV) and market status
- [x] 6.2 Key tests: explicit route key, empty symbol segment, search normalization, default provider per capability, `channel` ignored over HTTP
- [x] 6.3 Policy tests: new TTLs, TTL 0, no extension for new routes, market-status cap before 09:30 ET
- [x] 6.4 MCP tests: cache hit, `refresh: true`, Redis down fail-open, errors not cached, disabled cache, uncached live tools
- [x] 6.5 Never-cached tests: `/prices/{symbol}/last`, `/providers`, `/health` carry no `X-FastAPI-Cache` header
- [x] 6.6 Admin tests: status key counts, clear per new scope incl. MCP keys, policy update for new fields, 422 on invalid values
- [x] 6.7 `uv run ruff check app/`, `python skills/lint_check.py --all`, `uv run pytest --maxfail=1 --disable-warnings`
- [x] 6.8 Manual check with Docker Compose: `redis-cli --scan --pattern 'mdh:*'` shows the expected key names for HTTP and MCP calls

### Verification checkpoint (2026-11-06)

- 147 focused cache, market-hours, admin-cache and MCP-tool tests passed.
- `uv run ruff check app/` and Ruff checks for the changed test files passed.
- Admin production build and lint passed (existing bundle-size warning); no UI test script is configured in `admin/package.json`.
- Fixed two pre-existing I001 import-order errors in `tests/unit/test_lseg_provider.py` and `tests/unit/test_services.py` with user approval. Full application/test lint now passes.
- Full pytest suite passed: 446 passed, 21 skipped, 12 warnings.
- Isolated Compose project `mdh-cache-coverage-verification` on port 19091 passed all HTTP/MCP probes using fake providers and real Redis. `redis-cli --scan --pattern 'mdh:*'` confirmed all six route keys, empty-symbol keys, normalized search keys and `channel=mcp` entries. Counts after probing: chains 3, history 3, profiles 2, search 2, news 3, market status 2. Provider logs confirmed one live call per channel/format key.
- README/CHANGELOG updated for extended coverage, never-cached endpoints and repeatable Compose verification.
