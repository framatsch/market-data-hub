"""Tests for the MCP FastAPI router (app/api/mcp.py)."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient  # noqa: F401 — used in TestMcpSse
from httpx import AsyncClient, ASGITransport

from app.api.mcp import router, _dispatch, TOOL_REGISTRY, TOOL_HANDLERS, _ACTIVE_STREAMS
from app.utils.errors import AppError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(mcp_enabled: bool = True) -> FastAPI:
    """Build a minimal FastAPI app with (or without) the MCP router."""
    app = FastAPI()
    if mcp_enabled:
        app.include_router(router)
    return app


# ---------------------------------------------------------------------------
# Unit: _dispatch
# ---------------------------------------------------------------------------

class TestDispatch:
    """Unit tests for _dispatch — no HTTP layer involved."""

    @pytest.mark.asyncio
    async def test_tools_list_returns_registry(self):
        result = await _dispatch("tools/list", {})
        assert "tools" in result
        tool_names = [t["name"] for t in result["tools"]]
        assert "get_last_price" in tool_names
        assert "get_historical_prices" in tool_names
        assert "get_option_chain" in tool_names
        assert "search_companies" in tool_names
        assert len(result["tools"]) == len(TOOL_REGISTRY)

    @pytest.mark.asyncio
    async def test_tools_call_dispatches_to_handler(self):
        mock_handler = AsyncMock(return_value={"content": [{"type": "text", "text": "ok"}]})
        with patch.dict(TOOL_HANDLERS, {"mock_tool": mock_handler}):
            result = await _dispatch("tools/call", {"name": "mock_tool", "arguments": {"x": 1}})
        mock_handler.assert_awaited_once_with({"x": 1})
        assert result == {"content": [{"type": "text", "text": "ok"}]}

    @pytest.mark.asyncio
    async def test_tools_call_unknown_tool_raises(self):
        with pytest.raises(AppError) as exc_info:
            await _dispatch("tools/call", {"name": "nonexistent_tool", "arguments": {}})
        assert exc_info.value.code == "UNKNOWN_TOOL"

    @pytest.mark.asyncio
    async def test_unknown_method_raises(self):
        with pytest.raises(AppError) as exc_info:
            await _dispatch("resources/list", {})
        assert exc_info.value.code == "UNKNOWN_METHOD"


# ---------------------------------------------------------------------------
# Integration: GET /mcp/sse
# ---------------------------------------------------------------------------

class TestMcpSse:
    """Tests for the SSE session/routing logic."""

    @pytest.mark.asyncio
    async def test_sse_endpoint_event_format(self):
        """
        The SSE generator must emit an 'endpoint' event as its very first yield,
        containing a valid /mcp/messages?session_id=<uuid> URL.

        We test this by calling the route handler directly and consuming
        exactly the first item from the async generator it returns.
        """
        from starlette.requests import Request
        from starlette.testclient import TestClient
        from app.api.mcp import mcp_sse, _ACTIVE_STREAMS

        # Build a minimal scope for a GET /mcp/sse request
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/mcp/sse",
            "query_string": b"",
            "headers": [],
        }

        # We need a real Request object but we won't actually stream — we just
        # call the handler and read the first chunk from the streaming body.
        import uuid as _uuid

        sessions_before = set(_ACTIVE_STREAMS.keys())

        # Call the route function (returns a StreamingResponse)
        fake_request = Request(scope)
        response = await mcp_sse(fake_request)

        assert response.media_type == "text/event-stream"
        assert response.headers.get("cache-control") == "no-cache"

        # Read the first event from the async generator body
        body_iter = response.body_iterator
        first_chunk = await body_iter.__anext__()
        first_text = first_chunk if isinstance(first_chunk, str) else first_chunk.decode()

        assert "event: endpoint" in first_text
        assert "/mcp/messages?session_id=" in first_text

        # A new session should have been registered
        new_sessions = set(_ACTIVE_STREAMS.keys()) - sessions_before
        assert len(new_sessions) == 1

        # Clean up
        for sid in new_sessions:
            _ACTIVE_STREAMS.pop(sid, None)

    def test_mcp_disabled_returns_404(self):
        """When MCP router is not mounted, /mcp/sse must 404."""
        from starlette.testclient import TestClient
        app = _make_app(mcp_enabled=False)
        client = TestClient(app)
        response = client.get("/mcp/sse")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Integration: POST /mcp/messages
# ---------------------------------------------------------------------------

class TestMcpMessages:
    """Integration tests for the JSON-RPC message endpoint."""

    @pytest.mark.asyncio
    async def test_tool_result_pushed_to_sse_queue(self):
        """
        POST a tools/call to /mcp/messages and verify the result is pushed
        into the SSE queue for that session.
        """
        # Pre-register a session with a real asyncio.Queue
        session_id = "test-session-123"
        queue: asyncio.Queue = asyncio.Queue()
        _ACTIVE_STREAMS[session_id] = queue

        mock_handler = AsyncMock(return_value={"content": [{"type": "text", "text": "42.00"}]})

        app = _make_app()
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                with patch.dict(TOOL_HANDLERS, {"get_last_price": mock_handler}):
                    resp = await client.post(
                        f"/mcp/messages?session_id={session_id}",
                        json={
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "tools/call",
                            "params": {"name": "get_last_price", "arguments": {"symbol": "AAPL"}},
                        },
                    )
            assert resp.status_code == 202
            assert not queue.empty()
            sse_event = await queue.get()
            assert "event: message" in sse_event
            data_line = [l for l in sse_event.splitlines() if l.startswith("data:")][0]
            payload = json.loads(data_line[len("data:"):].strip())
            assert payload["id"] == 1
            assert payload["result"]["content"][0]["text"] == "42.00"
        finally:
            _ACTIVE_STREAMS.pop(session_id, None)

    @pytest.mark.asyncio
    async def test_app_error_returns_error_in_sse(self):
        """AppErrors from handlers must be serialised into the SSE error field."""
        session_id = "test-session-err"
        queue: asyncio.Queue = asyncio.Queue()
        _ACTIVE_STREAMS[session_id] = queue

        app = _make_app()
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    f"/mcp/messages?session_id={session_id}",
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {"name": "nonexistent_tool", "arguments": {}},
                    },
                )
            assert resp.status_code == 202
            sse_event = await queue.get()
            data_line = [l for l in sse_event.splitlines() if l.startswith("data:")][0]
            payload = json.loads(data_line[len("data:"):].strip())
            assert "error" in payload
            assert payload["error"]["code"] == "UNKNOWN_TOOL"
        finally:
            _ACTIVE_STREAMS.pop(session_id, None)

    @pytest.mark.asyncio
    async def test_unknown_session_returns_202_no_crash(self):
        """
        If no SSE session matches, the server should still return 202
        (response is silently dropped as per design).
        """
        app = _make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/mcp/messages?session_id=unknown-session",
                json={"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
            )
        assert resp.status_code == 202
