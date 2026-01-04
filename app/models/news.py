"""News article models."""

from datetime import datetime, date
from typing import List, Optional, Dict
from pydantic import BaseModel, Field


class NewsArticle(BaseModel):
    """Single news article."""

    article_id: str = Field(..., description="Format: {provider}:{native_id}")
    title: str
    summary: str
    published_at: datetime
    source: str
    url: str
    full_text: Optional[str] = Field(None, description="Full article text if available")
    category: Optional[str] = Field(
        None, description="Category: earnings, merger, product, legal, etc."
    )
    # Extra fields (Finnhub specific)
    image: Optional[str] = Field(None, description="Image URL (Finnhub)")
    sentiment: Optional[Dict[str, float]] = Field(
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

    data: List[NewsArticle]
    meta: NewsMetadata
