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
from app.providers.lseg import LSEGProvider

@pytest.fixture
def lseg_provider():
    with patch("app.providers.lseg.REFINITIV_AVAILABLE", True):
        with patch("app.providers.lseg.rd"):
            with patch("app.providers.lseg.historical_pricing") as mock_hp:
                # Setup Intervals mock
                mock_hp.Intervals.MINUTE = "PT1M"
                mock_hp.Intervals.DAILY = "P1D"
                provider = LSEGProvider()
                yield provider

def test_map_interval_all_lseg(lseg_provider):
    from app.providers.lseg import historical_pricing
    from app.utils.errors import ProviderError
    
    assert lseg_provider._map_interval("1m") == historical_pricing.Intervals.MINUTE
    assert lseg_provider._map_interval("1d") == historical_pricing.Intervals.DAILY
    
    with pytest.raises(ProviderError):
        lseg_provider._map_interval("unknown")
