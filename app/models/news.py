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

"""News article models."""

from datetime import date, datetime

from pydantic import BaseModel, Field


class NewsArticle(BaseModel):
    """Single news article."""

    article_id: str = Field(..., description="Format: {provider}:{native_id}")
    title: str
    summary: str
    published_at: datetime
    source: str
    url: str
    full_text: str | None = Field(None, description="Full article text if available")
    category: str | None = Field(
        None, description="Category: earnings, merger, product, legal, etc."
    )
    # Extra fields (Finnhub specific)
    image: str | None = Field(None, description="Image URL (Finnhub)")
    sentiment: dict[str, float] | None = Field(
        None, description="Sentiment scores: {positive, negative, neutral} (Finnhub)"
    )


class NewsMetadata(BaseModel):
    """Pagination and query metadata for news response."""

    total: int
    limit: int
    offset: int
    has_more: bool
    provider: str
    from_date: date
    to_date: date


class NewsResponse(BaseModel):
    """Standardized news response with pagination."""

    data: list[NewsArticle]
    meta: NewsMetadata
