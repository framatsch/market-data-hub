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
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.config import settings

# Skip if LSEG not configured
pytestmark = pytest.mark.skipif(
    not settings.LSEG_APP_KEY or settings.LSEG_APP_KEY == "stub-key",
    reason="LSEG credentials not configured"
)

@pytest.fixture
async def async_client():
    """Async test client with MCP enabled."""
    original_mcp_enabled = settings.MCP_ENABLED
    settings.MCP_ENABLED = True
    
    from app.api.mcp import router as mcp_router
    if not any(route.path.startswith("/mcp") for route in app.routes):
        app.include_router(mcp_router)
        
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    
    settings.MCP_ENABLED = original_mcp_enabled

@pytest.mark.integration
class TestMCPFlow:
    """Tests the full MCP SSE + JSON-RPC flow."""

    @pytest.mark.asyncio
    async def test_mcp_tools_list(self, async_client):
        """Test listing available MCP tools."""
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

    @pytest.mark.asyncio
    async def test_mcp_get_aapl_price_lseg(self, async_client):
        """Test getting AAPL price via MCP using LSEG provider."""
        # Note: This might still fail if LSEG is not available or connection fails,
        # but the flow itself is tested.
        
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
                    "arguments": {"symbol": "AAPL"}
                }
            }
            # We add a timeout to the post as well
            response = await async_client.post(f"/mcp/messages?session_id={session_id}", json=payload)
            assert response.status_code == 202
            
            # Wait for result with a timeout
            try:
                result = None
                async with asyncio.timeout(10.0): # 10s timeout for LSEG response
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
                assert "last_price" in quote
            except TimeoutError:
                pytest.fail("Timed out waiting for MCP response from LSEG")
