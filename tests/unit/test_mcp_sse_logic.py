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

import pytest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from app.api.mcp import mcp_sse

@pytest.mark.asyncio
async def test_mcp_sse_generator():
    mock_request = MagicMock()
    # Call the endpoint to get the StreamingResponse
    response = await mcp_sse(mock_request)
    
    # Extract the generator
    generator = response.body_iterator
    
    # 1. First event should be endpoint
    first_event = await anext(generator)
    assert "event: endpoint" in first_event
    
    # 2. Test keepalive by mocking asyncio.wait_for to timeout
    with patch("app.api.mcp.asyncio.wait_for", side_effect=asyncio.TimeoutError):
        # We need to break the infinite loop in the generator for the test
        # but let's just take one more item
        keepalive = await anext(generator)
        assert ": keepalive" in keepalive
