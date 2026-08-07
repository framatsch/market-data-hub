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

from datetime import date, timedelta

import pytest

from app.providers.mock_news import MockNewsProvider
from app.utils.errors import DataNotFoundError


@pytest.fixture
def mock_news_provider():
    return MockNewsProvider()

@pytest.mark.asyncio
async def test_get_company_news_success(mock_news_provider):
    to_date = date.today()
    from_date = to_date - timedelta(days=10)
    
    articles = await mock_news_provider.get_company_news("AAPL", from_date, to_date)
    assert len(articles) > 0
    assert articles[0].title != ""

@pytest.mark.asyncio
async def test_get_company_news_not_found(mock_news_provider):
    with pytest.raises(DataNotFoundError):
        await mock_news_provider.get_company_news("UNKNOWN", date.today(), date.today())

@pytest.mark.asyncio
async def test_get_company_news_category_filter(mock_news_provider):
    to_date = date.today()
    from_date = to_date - timedelta(days=10)
    
    articles = await mock_news_provider.get_company_news("AAPL", from_date, to_date, category="earnings")
    for a in articles:
        assert a.category == "earnings"
