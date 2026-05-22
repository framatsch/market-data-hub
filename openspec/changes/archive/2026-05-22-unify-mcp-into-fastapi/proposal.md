## Why

The current MCP implementation runs as a **separate process on port 8001** using FastMCP, with only a single stub health-check tool — none of the real market data functionality is exposed via MCP. This creates operational overhead (two processes, two ports) and requires duplicating provider access if real tools are ever added. The goal of `mcp_impl.md` is to collapse both servers into a single Uvicorn process, exposing MCP as a `/mcp/*` router within FastAPI.

## What Changes

- Remove `FastMCP` and the second server thread/process from `app/main.py`
- Add `MCP_ENABLED` feature flag to `app/config.py`
- Add a native FastAPI router `app/api/mcp.py` with SSE (`/mcp/sse`) and JSON-RPC POST (`/mcp/messages`) endpoints
- Register all market-data tools (prices, options, company, news) via an in-process `TOOL_REGISTRY` / `TOOL_HANDLERS` dict
- Single container, single port (8000) — deploy with `MCP_ENABLED=true`
- **BREAKING**: MCP endpoint moves from `localhost:8001` → `localhost:8000/mcp/`

## Capabilities

### New Capabilities

- `mcp-router`: FastAPI router at `/mcp/*` implementing MCP SSE transport and JSON-RPC message dispatch
- `mcp-market-data-tools`: MCP tool definitions and handlers for prices, options, company profiles, and news backed by existing providers

### Modified Capabilities

<!-- No existing spec-level requirements change — the HTTP REST API is untouched -->

## Impact

- `app/main.py` — remove dual-process startup, add conditional MCP router mount
- `app/config.py` — add `MCP_ENABLED: bool = False`
- `app/api/mcp.py` — new file (SSE transport + JSON-RPC dispatch)
- `pyproject.toml` / `uv.lock` — `fastmcp` dependency can be removed
- Docker / CI — single port exposed; `MCP_ENABLED` env var documented
