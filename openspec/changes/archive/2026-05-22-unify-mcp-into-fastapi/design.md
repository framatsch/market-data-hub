## Context

The app currently boots two servers: FastAPI on port 8000 (in a daemon thread) and FastMCP on port 8001 (on the main thread). The MCP server has only a single stub tool. All real market data functionality lives exclusively in FastAPI routes backed by IBKR, LSEG, and Finnhub providers. The proposal (`mcp_impl.md`) defines a target where MCP runs as a FastAPI sub-router on the same port, using SSE + JSON-RPC, with all market data tools wired directly to the existing provider/service layer.

## Goals / Non-Goals

**Goals:**
- Single Uvicorn process, single port (8000), for both REST and MCP traffic
- `MCP_ENABLED` feature flag (default `false`) — MCP is opt-in
- `/mcp/sse` SSE transport for MCP notifications and keepalives
- `/mcp/messages` JSON-RPC endpoint for tool calls
- MCP tools covering: last price, historical prices, option chain, option quote, company profile, company search, news
- Re-use existing provider registry and services — no duplication

**Non-Goals:**
- MCP authentication (PAT-based auth exists but is out of scope for this change)
- Rate limiting on `/mcp/*`
- SSE reconnect / Last-Event-ID handling
- Removing the `fastmcp` package from the dependency tree (can be done separately)

## Decisions

### 1. In-process router vs. separate process

**Chosen**: FastAPI `APIRouter` mounted under `/mcp` prefix.

**Rationale**: Shares the event loop, DB session pool, provider instances, and settings object. Eliminates the dual-port footprint and the code duplication that would accumulate as tools are added.

**Alternative considered**: Keep FastMCP but proxy through FastAPI. Rejected — adds latency, still requires two listening sockets.

### 2. Session routing via in-memory dict

**Chosen**: `_ACTIVE_STREAMS: dict[str, asyncio.Queue[str]]` keyed on `session_id` UUID.

**Rationale**: Zero external dependency, trivial to reason about for a single-instance deployment. Session ID is returned to the client in the first SSE `endpoint` event; subsequent POST requests include it as a query param.

**Alternative considered**: Redis pub/sub for multi-instance. Out of scope — the market data hub is single-instance and doesn't require horizontal scaling of the MCP layer.

### 3. Tool dispatch via explicit registry

**Chosen**: `TOOL_REGISTRY` (list of MCP tool descriptors) + `TOOL_HANDLERS` (dict of `async def (args, db) -> dict`).

**Rationale**: Explicit and grep-able. Each tool is a plain async function — easy to test in isolation, easy to add or remove.

**Alternative considered**: Auto-discovery via decorators (FastMCP style). Rejected — we lose the explicit control over the registry response for `tools/list`.

### 4. Provider access in tool handlers

**Chosen**: Tool handlers import from `app.providers.registry` and call the same service functions used by FastAPI routes.

**Rationale**: No duplication. If a provider changes (e.g., LSEG rate limiting), MCP tools automatically benefit.

## Risks / Trade-offs

- **Memory leak on client disconnect** — if a client opens `/mcp/sse` and disconnects without the generator reaching its `finally` block (e.g., server restart), the session remains in `_ACTIVE_STREAMS`. Mitigation: `finally` block in the async generator cleans up; add a periodic sweep task if needed.
- **Blocking sync providers in the event loop** — LSEG provider is synchronous. Existing FastAPI routes already run it via `asyncio.to_thread`. MCP tool handlers for LSEG must do the same.
- **SSE buffering by reverse proxies** — nginx/Caddy must set `X-Accel-Buffering: no` and disable proxy buffering for `/mcp/sse`. The response already sets this header; operator must configure the proxy.
- **Feature flag off by default** — `/mcp/*` routes only mount when `MCP_ENABLED=true`. This avoids accidental exposure in environments where MCP clients are not configured.

## Migration Plan

1. Merge this change behind `MCP_ENABLED=false` (no behaviour change for existing deployments)
2. Internal testing: set `MCP_ENABLED=true` and point an MCP client at `http://localhost:8000/mcp/sse`
3. Update any client configurations that previously pointed at `:8001` to `:8000/mcp/`
4. After validation, make `MCP_ENABLED=true` the default in production `docker-compose.yml`

**Rollback**: Set `MCP_ENABLED=false`. No schema or data migrations involved.

## Open Questions

- Should `tools/list` be available even when only the health tool is registered, or should an empty tool list be an error? (Lean: always return the list, even if empty)
- Do we need per-tool error handling that returns MCP-formatted errors vs. raising HTTP exceptions?
