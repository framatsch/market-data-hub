# market-data-hub - FastAPI data service for market and company data
# Copyright (C) 2026  Market Data Hub Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Tests for the MCP FastAPI router (app/api/mcp.py)."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient  # noqa: F401 — used in TestMcpSse
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient as StarletteTestClient

from app.api.mcp import (
    _ACTIVE_STREAMS,
    TOOL_HANDLERS,
    TOOL_REGISTRY,
    _dispatch,
    metadata_router,
    router,
)
from app.utils.errors import AppError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(mcp_enabled: bool = True) -> FastAPI:
    """Build a minimal FastAPI app with (or without) the MCP router."""
    app = FastAPI()
    if mcp_enabled:
        app.include_router(metadata_router)
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

        from app.api.mcp import _ACTIVE_STREAMS, mcp_sse

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
        app = _make_app(mcp_enabled=False)
        client = StarletteTestClient(app)
        response = client.get("/mcp/sse")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_root_mcp_get_starts_sse_transport(self):
        """GET /mcp is accepted for remote clients configured with the base MCP URL."""
        from starlette.requests import Request

        from app.api.mcp import _ACTIVE_STREAMS, mcp_sse

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/mcp",
            "query_string": b"",
            "headers": [],
        }
        sessions_before = set(_ACTIVE_STREAMS.keys())
        response = await mcp_sse(Request(scope))

        assert response.media_type == "text/event-stream"
        first_chunk = await response.body_iterator.__anext__()
        first_text = first_chunk if isinstance(first_chunk, str) else first_chunk.decode()
        assert "event: endpoint" in first_text

        for sid in set(_ACTIVE_STREAMS.keys()) - sessions_before:
            _ACTIVE_STREAMS.pop(sid, None)


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
            data_line = next(line for line in sse_event.splitlines() if line.startswith("data:"))
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
            data_line = next(line for line in sse_event.splitlines() if line.startswith("data:"))
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


class TestMcpStreamableHttp:
    """Regression tests for Claude remote MCP clients posting to /mcp."""

    @pytest.mark.asyncio
    async def test_post_root_mcp_returns_json_rpc_response(self):
        app = _make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["jsonrpc"] == "2.0"
        assert payload["id"] == 1
        assert "tools" in payload["result"]

    @pytest.mark.asyncio
    async def test_post_root_mcp_notification_returns_202(self):
        app = _make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            )

        assert response.status_code == 202

    @pytest.mark.asyncio
    async def test_oauth_protected_resource_metadata_is_public(self):
        app = _make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://example.com") as client:
            response = await client.get("/.well-known/oauth-protected-resource/mcp")

        assert response.status_code == 200
        payload = response.json()
        assert payload["resource"] == "https://example.com/mcp"
        assert payload["authorization_servers"] == []
