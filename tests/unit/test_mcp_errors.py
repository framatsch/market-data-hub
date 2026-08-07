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

from unittest.mock import AsyncMock, patch

import pytest

from app.api.mcp import _dispatch
from app.utils.errors import ProviderError


@pytest.mark.asyncio
async def test_dispatch_tool_error():
    # Patch the dict itself and its get method
    with patch("app.api.mcp.TOOL_HANDLERS") as mock_handlers:
        mock_handler = AsyncMock(side_effect=ProviderError("Test Error"))
        mock_handlers.get.return_value = mock_handler
        
        # Method "tools/call" with param "name" triggers TOOL_HANDLERS
        with pytest.raises(ProviderError):
            await _dispatch("tools/call", {"name": "get_last_price", "arguments": {"symbol": "AAPL"}})

@pytest.mark.asyncio
async def test_dispatch_unknown_method():
    from app.utils.errors import AppError
    with pytest.raises(AppError) as exc:
        await _dispatch("unknown_method", {})
    assert "Unknown method" in exc.value.message

