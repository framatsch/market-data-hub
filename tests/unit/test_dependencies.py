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
from unittest.mock import MagicMock, patch
from app.dependencies import (
    get_price_service, get_company_service, 
    get_options_service, get_news_service
)

def test_get_price_service():
    service = get_price_service()
    assert service is not None

def test_get_company_service():
    service = get_company_service()
    assert service is not None

def test_get_options_service():
    service = get_options_service()
    assert service is not None

def test_get_news_service():
    from app.services.news_service import NewsService
    service = get_news_service()
    assert isinstance(service, NewsService)
