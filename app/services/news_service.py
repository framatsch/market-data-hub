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

from datetime import date
from typing import Any

import structlog

from app.models.news import NewsArticle
from app.providers.registry import get_registry


class NewsService:
    def __init__(self, registry: Any = None) -> None:
        self.registry = registry or get_registry()

    async def get_company_news(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
        provider_name: str | None = None,
        limit: int = 20,
        offset: int = 0,
        language: str = "en",
        category: str | None = None,
    ) -> list[NewsArticle]:
        provider = self.registry.get_news_provider(provider_name)
        structlog.contextvars.bind_contextvars(provider=provider.name)
        return await provider.get_company_news(
            symbol=symbol,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            offset=offset,
            language=language,
            category=category,
        )


news_service = NewsService()
