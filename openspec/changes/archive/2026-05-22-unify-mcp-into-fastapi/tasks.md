## 1. Config & Feature Flag

- [x] 1.1 Add `MCP_ENABLED: bool = False` field to `Settings` in `app/config.py`
- [x] 1.2 Add `MCP_ENABLED` to `.env.example` with comment explaining the flag

## 2. MCP Router Scaffold

- [x] 2.1 Create `app/api/mcp.py` with `APIRouter(prefix="/mcp", tags=["mcp"])`
- [x] 2.2 Add `_ACTIVE_STREAMS: dict[str, asyncio.Queue[str]]` session registry
- [x] 2.3 Implement `GET /mcp/sse` endpoint with SSE stream, session UUID, keepalive, and cleanup in `finally`
- [x] 2.4 Implement `POST /mcp/messages` endpoint accepting `session_id` query param and JSON-RPC body
- [x] 2.5 Implement `_dispatch(method, params, db)` routing `tools/list` and `tools/call`

## 3. Market Data Tool Handlers

- [x] 3.1 Implement `get_last_price` handler — calls default price provider via `app/providers/registry.py`
- [x] 3.2 Implement `get_historical_prices` handler — accepts `symbol`, `start_date`, `end_date`
- [x] 3.3 Implement `get_option_chain` handler — calls default options provider
- [x] 3.4 Implement `get_option_quote` handler — accepts `symbol` and `option_id`
- [x] 3.5 Implement `get_company_profile` handler — calls default company provider
- [x] 3.6 Implement `search_companies` handler — accepts `query` string
- [x] 3.7 Implement `get_company_news` handler — calls default news provider
- [x] 3.8 Add error handling in `_dispatch`: catch `AppError` and generic exceptions, return `{"error": {"message": "..."}}` in SSE

## 4. Tool Registry

- [x] 4.1 Define `TOOL_REGISTRY` list with MCP-schema descriptors for all 7 tools (name, description, inputSchema)
- [x] 4.2 Define `TOOL_HANDLERS` dict mapping tool names to handler functions

## 5. FastAPI Integration

- [x] 5.1 In `app/main.py`, conditionally include the MCP router: `if settings.MCP_ENABLED: app.include_router(mcp_router)`
- [x] 5.2 Remove the `FastMCP` server instance and the dual-thread startup logic from `app/main.py`

## 6. Tests

- [x] 6.1 Write unit tests for `_dispatch` with mocked handlers (tools/list, tools/call, unknown method)
- [x] 6.2 Write integration test for `GET /mcp/sse` — verify first SSE event contains `endpoint` with session URL
- [x] 6.3 Write integration test for `POST /mcp/messages` — verify tool result appears in SSE queue
- [x] 6.4 Verify `MCP_ENABLED=false` results in 404 on `/mcp/sse`

## 7. Documentation & Cleanup

- [x] 7.1 Update `README.md` — replace dual-port startup section, document `MCP_ENABLED` env var and new MCP endpoint URL
- [x] 7.2 Update `AGENTS.md` — fix "Running the Service" section, remove reference to port 8001
- [x] 7.3 Optionally remove `fastmcp` from `pyproject.toml` if no other code uses it
