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

"""Mock news provider for testing and development."""

from datetime import datetime, timezone, date, timedelta
from typing import List, Optional
from app.models.news import NewsArticle
from app.providers.base import BaseNewsProvider
from app.utils.errors import DataNotFoundError, ProviderError
import logging

logger = logging.getLogger(__name__)


class MockNewsProvider(BaseNewsProvider):
    """Mock provider for testing news functionality without external dependencies."""

    # Mock data for common stocks
    MOCK_NEWS_DB = {
        "AAPL": [
            {
                "id": "mock:aapl:001",
                "title": "Apple Reports Record Q4 Earnings",
                "summary": "Apple Inc. announced record-breaking quarterly earnings with strong iPhone sales.",
                "date": -1,  # days ago
                "source": "Reuters",
                "url": "https://www.reuters.com/tech/apple-earnings-2026",
                "category": "earnings",
            },
            {
                "id": "mock:aapl:002",
                "title": "Apple Expands AI Capabilities",
                "summary": "Apple announced new AI features for iPhone and Mac with on-device processing.",
                "date": -2,
                "source": "Bloomberg",
                "url": "https://www.bloomberg.com/apple-ai-2026",
                "category": "product",
            },
            {
                "id": "mock:aapl:003",
                "title": "Apple Acquires AI Startup",
                "summary": "Apple announced the acquisition of AI startup for undisclosed amount.",
                "date": -5,
                "source": "TechCrunch",
                "url": "https://www.techcrunch.com/apple-acquisition",
                "category": "merger",
            },
            {
                "id": "mock:aapl:004",
                "title": "Apple Faces EU Regulation",
                "summary": "European Union announces new regulations affecting Apple's app store policies.",
                "date": -7,
                "source": "Financial Times",
                "url": "https://www.ft.com/apple-eu-2026",
                "category": "legal",
            },
            {
                "id": "mock:aapl:005",
                "title": "Apple Stock Reaches New High",
                "summary": "Apple stock hits new 52-week high on strong earnings guidance.",
                "date": -3,
                "source": "CNBC",
                "url": "https://www.cnbc.com/apple-stock-2026",
                "category": None,
            },
        ],
        "MSFT": [
            {
                "id": "mock:msft:001",
                "title": "Microsoft Azure Revenue Surges",
                "summary": "Microsoft reports strong Azure cloud revenue growth driven by AI services.",
                "date": -1,
                "source": "Reuters",
                "url": "https://www.reuters.com/microsoft-azure-2026",
                "category": "earnings",
            },
            {
                "id": "mock:msft:002",
                "title": "Microsoft Copilot Integration Expands",
                "summary": "Microsoft announces Copilot integration across Office 365 and enterprise tools.",
                "date": -4,
                "source": "TechCrunch",
                "url": "https://www.techcrunch.com/microsoft-copilot-2026",
                "category": "product",
            },
        ],
        "GOOGL": [
            {
                "id": "mock:googl:001",
                "title": "Google Announces New Search Features",
                "summary": "Google launches AI-powered search features with natural language understanding.",
                "date": -2,
                "source": "Bloomberg",
                "url": "https://www.bloomberg.com/google-search-2026",
                "category": "product",
            },
        ],
    }

    async def get_company_news(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
        limit: int = 20,
        offset: int = 0,
        language: str = "en",
        category: Optional[str] = None
    ) -> List[NewsArticle]:
        """Get mock news articles for a company."""
        try:
            # Check if symbol exists in mock database
            symbol_upper = symbol.upper()
            if symbol_upper not in self.MOCK_NEWS_DB:
                raise DataNotFoundError("Ticker", symbol)

            # Get mock articles
            mock_articles = self.MOCK_NEWS_DB[symbol_upper]

            # Filter by date range
            articles = []
            today = date.today()

            for article_data in mock_articles:
                # Calculate article date
                article_date = today + timedelta(days=article_data["date"])

                # Check if within date range
                if article_date < from_date or article_date > to_date:
                    continue

                # Filter by category if specified
                if category and article_data["category"] != category:
                    continue

                # Create NewsArticle
                article = NewsArticle(
                    article_id=article_data["id"],
                    title=article_data["title"],
                    summary=article_data["summary"],
                    published_at=datetime.combine(
                        article_date, datetime.min.time(), tzinfo=timezone.utc
                    ),
                    source=article_data["source"],
                    url=article_data["url"],
                    full_text=None,
                    category=article_data["category"],
                )
                articles.append(article)

            # Apply pagination
            articles = articles[offset : offset + limit]

            logger.info(f"Mock provider: returned {len(articles)} articles for {symbol}")
            return articles

        except DataNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Mock news error for {symbol}: {e}")
            raise ProviderError(f"Failed to fetch news from mock provider: {str(e)}")
