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
import pandas as pd
from unittest.mock import patch, MagicMock
from datetime import date
from app.providers.lseg import LSEGProvider

@pytest.fixture
def lseg_provider(monkeypatch):
    with patch("app.providers.lseg.REFINITIV_AVAILABLE", True):
        # We need to mock the entire rd structure and the session manager
        mock_headlines = MagicMock()

        # Define a mock rd structure
        mock_rd = MagicMock()
        mock_rd.news.get_headlines = mock_headlines

        # Monkeypatch the module-level 'rd' in app.providers.lseg
        import app.providers.lseg as lseg_mod
        monkeypatch.setattr(lseg_mod, "rd", mock_rd)

        provider = LSEGProvider()
        # Mock RIC lookup
        provider._ticker_to_ric = MagicMock(return_value="AAPL.O")

        yield provider, mock_headlines

@pytest.mark.asyncio
async def test_get_company_news_lseg(lseg_provider):
    provider, mock_headlines = lseg_provider

    # Mock news DataFrame
    df = pd.DataFrame([{
        "storyId": "123",
        "headline": "Test Headline",
        "versionCreated": "2024-01-01T12:00:00Z",
        "sourceCode": "RTRS",
        "subjects": ["EARN"]
    }])
    mock_headlines.return_value = df

    articles = await provider.get_company_news("AAPL", date(2024, 1, 1), date(2024, 1, 2))
    assert len(articles) == 1
    assert articles[0].title == "Test Headline"
    assert articles[0].category == "earnings"

@pytest.mark.asyncio
async def test_get_company_news_lseg_empty(lseg_provider):
    provider, mock_headlines = lseg_provider
    mock_headlines.return_value = pd.DataFrame()

    articles = await provider.get_company_news("AAPL", date(2024, 1, 1), date(2024, 1, 2))
    assert len(articles) == 0
