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
            provider = LSEGProvider()
            return provider

def test_ticker_to_ric_cleanup(lseg_provider):
    mock_search = MagicMock()
    mock_df = MagicMock()
    mock_df.empty = False
    # First one is "dirty" (futures continuation), second is "clean"
    mock_df.__getitem__.return_value.tolist.return_value = ["AAPL.c1", "AAPL.O"]
    mock_search.get_data.return_value.data.df = mock_df
    
    with patch("app.providers.lseg.search.Definition", return_value=mock_search):
        assert lseg_provider._ticker_to_ric("AAPL") == "AAPL.O"

def test_ticker_to_ric_fallback(lseg_provider):
    mock_search = MagicMock()
    mock_df = MagicMock()
    mock_df.empty = False
    # All are "dirty"
    mock_df.__getitem__.return_value.tolist.return_value = ["AAPL.c1"]
    mock_search.get_data.return_value.data.df = mock_df
    
    with patch("app.providers.lseg.search.Definition", return_value=mock_search):
        assert lseg_provider._ticker_to_ric("AAPL") == "AAPL.c1"


def test_is_retryable_error(lseg_provider):
    assert lseg_provider._is_retryable_error(Exception("Connection timeout")) is True
    assert lseg_provider._is_retryable_error(Exception("Not found")) is False
    # In a real app we might have specific non-retryable errors
    # but the current implementation seems to return True for all
