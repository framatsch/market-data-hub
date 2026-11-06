## Context

`add-redis-cache-layer` (archived, main spec `response-caching`) introduced a fail-open Redis response cache built on `fastapi-cache2`:

- `app/cache.py` provides the `@cache(expire=...)` adapter, `mdh_key_builder` (`mdh:{route_path}:{symbol}:{query_params}`), `CachePolicy` (runtime TTLs in `system_settings`, US session model), `FailOpenRedisBackend` (30 s cooldown), `CacheControlMiddleware`, status and `SCAN`/`UNLINK` clearing.
- Only `GET /options/{symbol}/chain` and `GET /prices/{symbol}/history` are decorated.
- The MCP tools in `app/api/mcp.py` instantiate `PriceService`/`OptionsService`/`CompanyService` directly (and `get_company_news` calls the news provider directly), so they never pass through the HTTP decorator.

Endpoint audit (provider-backed reads):

| Endpoint / tool | Volatility | Decision |
|---|---|---|
| `/companies/{symbol}` | days | cache, 24 h |
| `/companies/search` | days | cache, 1 h |
| `/companies/{symbol}/news` | minutes | cache, 10 min |
| `/market-status` | changes at session transitions | cache, 60 s capped at next transition |
| `/prices/{symbol}/last`, `/options/{symbol}/quote/{id}` | seconds | never cache |
| `/health`, `/metrics`, `/providers`, `/api/admin/*`, WS | local state | never cache |
| MCP tools mirroring the cached endpoints | as above | cache via shared backend |

## Goals / Non-Goals

**Goals:**
- Every slow-changing provider-backed read is protected by the cache, for HTTP and MCP alike.
- Reuse the existing backend, fail-open semantics, policy refresh and admin tooling — no second cache mechanism.
- Keep existing keys for option chains and historical prices byte-for-byte unchanged.

**Non-Goals:**
- Caching live quotes (`/prices/{symbol}/last`, option quotes) or WebSocket streams.
- Sharing entries between HTTP and MCP (see Decision 2).
- Changing the historical-prices TTL model (bar-state-aware rules stay as specified).
- Exchange-holiday calendars.

## Decisions

### 1. Explicit route key via the decorator, not path heuristics
`cache(expire=..., key="companies:profile")` passes the override as the `fastapi-cache2` namespace; `mdh_key_builder` uses it as `route_path` when present. Without it, `GET /companies/{symbol}` would yield `mdh:companies:AAPL:…`, and the clear pattern `mdh:companies:*` would also match search and news keys.
*Alternative:* rename by a lookup table inside the key builder — rejected, the route declaration is the natural place and keeps the mapping visible next to the TTL.

### 2. MCP caching through a `cached_call` helper with a `channel=mcp` marker
New helper in `app/cache.py`:

```python
async def cached_call(route_key, symbol, params, loader, *, refresh=False) -> Any
```

It builds the key with the same composition function as the HTTP builder (shared `_compose_key`, including provider defaulting and normalization), adds `channel=mcp`, reads/writes via `FastAPICache.get_backend()` and `MdhJsonCoder`, respects `FastAPICache.get_enable()`, skips the read on `refresh`, and never stores exceptions. TTL resolution happens inside `FailOpenRedisBackend.set()` from the key, exactly like HTTP.
*Why separate entries:* HTTP stores the `ResponseEnvelope`/`NewsResponse` JSON (or a CSV `Response`), MCP returns raw domain objects; MCP defaults also differ (news: last 7 days vs 30 days). Sharing would couple two output shapes and make keys fragile. Keeping `route_path` identical means clear scopes, provider filters, key counts and the TTL policy cover MCP automatically. `channel` is not a declared HTTP query parameter, so HTTP requests can never address MCP entries.
*Alternative:* move all caching into the service layer — rejected for this change: it would duplicate or replace the tested HTTP decorator path (HIT/MISS headers, `Cache-Control`, CSV responses) for no rate-limit benefit beyond what `cached_call` gives.

### 3. Policy: route → TTL table, extension limited to market data
`CachePolicyValues` gains `company_profile_seconds`, `company_search_seconds`, `company_news_seconds`, `market_status_seconds`. `CachePolicy.resolve` dispatches on the route key; the market-closed extension stays restricted to `options:chain` and `prices:history` — news is published overnight, and profile/search TTLs are already long. Settings-repository allowlist and `policy_defaults()` get the new keys.

### 4. Market status capped at the next session transition
`app/market_hours.py` gets `next_transition(now)` returning the next weekday 04:00/09:30/16:00/20:00 ET boundary. TTL = `min(market_status_seconds, seconds_until_transition)`; `0` when the result is below 1 s (served live).

### 5. Provider defaulting per full route key
The key builder's capability map moves from the first path segment to the route key: `options:chain` → options, `prices:history` and `market-status` → price, `companies:profile`/`companies:search` → company, `companies:news` → news.

### 6. Search query normalization
In the key only: `" ".join(q.split()).lower()`. The provider still receives the original `q`. Finnhub/LSEG/Polygon/IBKR symbol search are case-insensitive, so the first requester's casing does not change results.

### 7. News CSV as concrete `Response`
`StreamingResponse` has no `.body`, so `MdhJsonCoder` cannot store it. The existing adapter already copies cache headers onto concrete `Response`s (same pattern as history/chain CSV).

### 8. Scopes and key counts
`CacheScope` and `_PATTERNS` gain `company_profile` (`mdh:companies:profile:*`), `company_search` (`mdh:companies:search:*`), `company_news` (`mdh:companies:news:*`), `market_status` (`mdh:market-status:*`). `cache_status()` counts all scopes except `all`. The admin route and UI derive from `CacheScope`.

## Risks / Trade-offs

- [Company profile stale for up to 24 h after corporate actions] → admin clear scope `company_profile`; clients send `Cache-Control: no-cache`; MCP `refresh: true`.
- [News up to 10 min late, e.g. for earnings] → TTL runtime-configurable down to 0; forced refresh available.
- [Many unique search queries inflate Redis memory] → bounded by `maxmemory` + `allkeys-lru`; 1 h TTL.
- [Search normalization merges case variants for a hypothetical case-sensitive provider] → all current providers are case-insensitive; documented in the spec.
- [HTTP and MCP each fetch once per TTL (no sharing)] → at most 2× provider calls per TTL window instead of unbounded; acceptable.
- [Holidays not modeled for market-status cap] → cap is conservative (shorter TTL), never longer.

## Migration Plan

Additive. Deploy normally; new env vars have defaults, no stored settings migration. Existing option-chain/history entries remain valid. Rollback: redeploy previous image; new keys expire by TTL or via `POST /api/admin/cache/clear`.

## Open Questions

- None blocking. Possible follow-up: share HTTP/MCP entries by caching at the service layer if dashboard and agents frequently request identical data.
