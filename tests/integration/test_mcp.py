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

"""Integration tests for MCP (Model Context Protocol) endpoints."""

import pytest
import json
import asyncio
import threading
import uvicorn
import socket
import time
from httpx import AsyncClient
from app.main import app
from app.config import settings

import os

# Skip if LSEG not configured or if explicitly in CI
pytestmark = [
    pytest.mark.skipif(
        not settings.LSEG_APP_KEY or settings.LSEG_APP_KEY == "stub-key",
        reason="LSEG credentials not configured"
    ),
    pytest.mark.skipif(
        os.getenv("CI") == "true",
        reason="Skipping network-intensive integration test in CI"
    )
]

def get_free_port():
    """Find a free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]

@pytest.fixture(scope="module")
def server_port():
    return get_free_port()

@pytest.fixture(scope="module")
def real_server(server_port):
    """Run a real uvicorn server in a background thread."""
    original_mcp_enabled = settings.MCP_ENABLED
    settings.MCP_ENABLED = True
    
    from app.api.mcp import router as mcp_router
    if not any(route.path.startswith("/mcp") for route in app.routes):
        app.include_router(mcp_router)

    config = uvicorn.Config(app, host="127.0.0.1", port=server_port, log_level="warning")
    server = uvicorn.Server(config)
    
    thread = threading.Thread(target=server.run)
    thread.daemon = True
    thread.start()
    
    # Wait for server to start
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", server_port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.1)
    else:
        pytest.fail("Server failed to start")
        
    yield f"http://127.0.0.1:{server_port}"
    
    server.should_exit = True
    thread.join(timeout=2.0)
    settings.MCP_ENABLED = original_mcp_enabled

@pytest.fixture
async def async_client(real_server):
    """Async client pointing to the real background server."""
    async with AsyncClient(base_url=real_server, timeout=15.0) as client:
        yield client

@pytest.mark.integration
@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
class TestMCPFlow:
    """Tests the full MCP SSE + JSON-RPC flow."""

    async def test_mcp_tools_list(self, async_client):
        """Test listing available MCP tools."""
        try:
            async with asyncio.timeout(10.0):
                async with async_client.stream("GET", "/mcp/sse") as sse_response:
                    lines = sse_response.aiter_lines()
                    
                    # 1. Get session_id from endpoint event
                    session_id = None
                    async for line in lines:
                        if "data: /mcp/messages?session_id=" in line:
                            session_id = line.split("session_id=")[1].strip()
                            break
                    
                    assert session_id is not None
                    
                    # 2. Call tools/list
                    payload = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/list",
                        "params": {}
                    }
                    response = await async_client.post(f"/mcp/messages?session_id={session_id}", json=payload)
                    assert response.status_code == 202
                    
                    # 3. Wait for response in SSE stream
                    result = None
                    async for line in lines:
                        if line.startswith("data: {"):
                            result = json.loads(line[6:].strip())
                            break
                    
                    assert result is not None
                    assert result["id"] == 1
                    assert "tools" in result["result"]
                    assert any(t["name"] == "get_last_price" for t in result["result"]["tools"])
        except TimeoutError:
            pytest.fail("MCP Tools list test timed out")

    @pytest.mark.anyio
    async def test_mcp_get_aapl_price_lseg(self, async_client):
        """Test getting AAPL price via MCP using LSEG provider."""
        try:
            async with asyncio.timeout(20.0):
                async with async_client.stream("GET", "/mcp/sse") as sse_response:
                    lines = sse_response.aiter_lines()
                    
                    session_id = None
                    async for line in lines:
                        if "data: /mcp/messages?session_id=" in line:
                            session_id = line.split("session_id=")[1].strip()
                            break
                    
                    assert session_id is not None
                    
                    # Call get_last_price
                    payload = {
                        "jsonrpc": "2.0",
                        "id": "aapl-test",
                        "method": "tools/call",
                        "params": {
                            "name": "get_last_price",
                            "arguments": {"symbol": "AAPL", "provider": "lseg"}
                        }
                    }
                    response = await async_client.post(f"/mcp/messages?session_id={session_id}", json=payload)
                    assert response.status_code == 202
                    
                    # Wait for result
                    result = None
                    async for line in lines:
                        if line.startswith("data: {"):
                            result = json.loads(line[6:].strip())
                            break
                    
                    assert result is not None
                    if "error" in result:
                        pytest.fail(f"MCP Tool returned error: {result['error']}")
                    
                    assert result["id"] == "aapl-test"
                    content = result["result"]["content"][0]["text"]
                    quote = json.loads(content)
                    assert quote["symbol"] == "AAPL"
                    assert "price" in quote or "last_price" in quote
        except TimeoutError:
            pytest.fail("MCP Get Price test timed out")
