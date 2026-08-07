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

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.main import app, lifespan


@pytest.mark.asyncio
async def test_lifespan():
    # Mock registry shutdown
    mock_registry = MagicMock()
    mock_registry.shutdown = AsyncMock()
    mock_registry.reload_from_config = AsyncMock()
    
    with patch("app.providers.registry.registry", mock_registry):
        async with lifespan(app):
            # Startup protocol logic runs here
            pass
        
        # Verify shutdown called
        mock_registry.shutdown.assert_called_once()
