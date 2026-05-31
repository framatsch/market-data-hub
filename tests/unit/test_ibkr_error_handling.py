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
from unittest.mock import patch, MagicMock
from app.providers.ibkr import IBKRProvider

@pytest.fixture
def ibkr_provider():
    with patch("app.providers.ibkr.IB"):
        provider = IBKRProvider()
        return provider

def test_on_ib_error_level1(ibkr_provider):
    # Set to Level 1
    ibkr_provider._requested_market_data_type = 1
    # Error code 10091
    ibkr_provider._on_ib_error(1, 10091, "No subscription", None)
    assert ibkr_provider._level1_subscription_error is True

def test_handle_subscription_error(ibkr_provider):
    # Error code 10091: Requested market data is not subscribed
    assert ibkr_provider._handle_subscription_error("Error 10091: No subscription") is True
    # Implementation doesn't set flag here, it's done in _on_ib_error
    
    # Generic error
    assert ibkr_provider._handle_subscription_error("Generic error") is False

