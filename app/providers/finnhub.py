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

"""
Finnhub News Provider - Real-time company news with sentiment analysis
https://finnhub.io/docs/api/company-news
"""

import asyncio
import logging
import re
import time
from collections import deque
from datetime import UTC, date, datetime
from typing import Any

import httpx

from app.config import settings
from app.models.news import NewsArticle
from app.providers.base import BaseNewsProvider
from app.utils.errors import DataNotFoundError, ProviderConnectionError, ProviderError

logger = logging.getLogger(__name__)


class FinnhubProvider(BaseNewsProvider):
    """Finnhub provider for company news with sentiment analysis.

    Features:
    - Company news endpoint (symbol + date range)
    - Sentiment analysis (positive, negative, neutral)
    - Token bucket rate limiting (60 calls/min)
    - Async HTTP requests
    - Automatic category detection from headlines
    """

    def __init__(self) -> None:
        self._api_key: str | None = None
        self._api_key_configured = False

        # Sliding-window rate limiter (60 calls per minute).
        # No maxlen: manual popleft manages the window to avoid eviction races.
        self._rate_limit_per_min = settings.FINNHUB_RATE_LIMIT_PER_MIN
        self._request_times: deque[float] = deque()
        self._last_rate_limit_error: datetime | None = None

        # HTTP client
        self._client: httpx.AsyncClient | None = None

        # Category keywords for sentiment-based categorization
        self._category_keywords = {
            "earnings": [
                r"\bearnings?\b", r"\beps\b", r"\brev(enue)?\b", r"\bguidance\b",
                r"\bprofit\b", r"\bloss\b", r"\bmargin\b", r"\bshares?\b",
                r"\bdividend\b", r"\bq[1-4]\s*result", r"\bfiscal\b"
            ],
            "merger": [
                r"\b(m&a|merger|acquisition|acquires?|acquired|deal)\b",
                r"\btakeover\b", r"\bipo\b", r"\bspac\b", r"\bmarket cap\b",
                r"\b(buyout|buy[- ]?out)\b", r"\bcombination\b"
            ],
            "product": [
                r"\b(launch|release|announce|unveiled?|new\s+product)\b",
                r"\b(app|service|feature|update|version)\b", r"\bsoftware\b",
                r"\bhardware\b", r"\bdevice\b", r"\bplatform\b"
            ],
            "legal": [
                r"\b(lawsuit|sued|settlement|conviction|guilty)\b",
                r"\b(regulatory|fda|sec|antitrust|investigation)\b",
                r"\b(fine|penalty|compliance|illegal)\b", r"\blegal\b"
            ]
        }

        logger.info("FinnhubProvider initialized")

    async def _ensure_api_key(self) -> str:
        """Ensure API key is loaded from the encrypted key repository."""
        if self._api_key_configured and self._api_key:
            return self._api_key

        try:
            from app.admin.runtime import get_key_repository
            db_key = await get_key_repository().get("finnhub", "api_key")
            if db_key:
                self._api_key = db_key
                self._api_key_configured = True
                return self._api_key
        except Exception as e:
            logger.debug(f"Could not load Finnhub key from DB: {e}")

        raise ProviderError(
            "Finnhub API key not configured. Add it in the admin UI.",
            code="PROVIDER_NOT_AVAILABLE",
            details={"provider": "finnhub"}
        )

    # ========================================================================
    # HTTP Client Management
    # ========================================================================

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=settings.FINNHUB_BASE_URL,
                timeout=settings.PROVIDER_REQUEST_TIMEOUT
            )
        return self._client

    async def _close_client(self) -> None:
        """Close HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ========================================================================
    # Rate Limiting (Token Bucket)
    # ========================================================================

    async def _check_rate_limit(self) -> bool:
        """Check and enforce rate limit (60 calls/min).

        Returns:
            True if within rate limit, False if exceeded
        """
        now = time.time()

        # Remove timestamps older than 1 minute
        while self._request_times and now - self._request_times[0] > 60.0:
            self._request_times.popleft()

        # Check if at rate limit
        if len(self._request_times) >= self._rate_limit_per_min:
            self._last_rate_limit_error = datetime.now(UTC)
            logger.warning(
                f"Finnhub rate limit reached ({self._rate_limit_per_min}/min). "
                f"Next available at {self._request_times[0] + 60:.1f}s"
            )
            return False

        # Record this request
        self._request_times.append(now)
        return True

    # ========================================================================
    # Category Detection
    # ========================================================================

    def _detect_category(self, headline: str, summary: str | None = None, sentiment: dict[str, Any] | None = None) -> str | None:
        """Detect article category from headline/summary.

        Priority:
        1. Keyword matching in headline + summary
        2. Sentiment score as proxy (if no keywords found)
        3. None (neutral/unknown)
        """
        text = f"{headline} {summary or ''}".lower()

        # Try keyword matching first
        for category, keywords in self._category_keywords.items():
            for pattern in keywords:
                if re.search(pattern, text, re.IGNORECASE):
                    logger.debug(f"Category '{category}' detected for: {headline[:50]}")
                    return category

        # Fallback: use sentiment as proxy
        if sentiment:
            scores = sentiment
            if isinstance(scores, dict):
                positive = scores.get("positive", 0)
                negative = scores.get("negative", 0)
                _ = scores.get("neutral", 0)  # Not currently used in category detection

                # Strong negative sentiment → legal/regulatory issues
                if negative > 0.6:
                    logger.debug(f"Category 'legal' detected from negative sentiment for: {headline[:50]}")
                    return "legal"

                # Strong positive sentiment → product/earnings
                if positive > 0.6 and "launch" in text or "announce" in text:
                    return "product"

        return None

    # ========================================================================
    # Sentiment Parsing
    # ========================================================================

    def _parse_sentiment(self, sentiment_obj: dict[str, Any] | None) -> dict[str, float]:
        """Parse sentiment object into normalized format.

        Finnhub returns:
        {
            "positive": 0.8,
            "negative": 0.1,
            "neutral": 0.1
        }
        """
        if not sentiment_obj or not isinstance(sentiment_obj, dict):
            return {"positive": 0.0, "negative": 0.0, "neutral": 1.0}

        return {
            "positive": float(sentiment_obj.get("positive", 0.0)),
            "negative": float(sentiment_obj.get("negative", 0.0)),
            "neutral": float(sentiment_obj.get("neutral", 1.0))
        }

    # ========================================================================
    # API Methods
    # ========================================================================

    async def test_connection(self) -> dict[str, Any]:
        """Validate Finnhub API key with a lightweight quote request."""
        try:
            api_key = await self._ensure_api_key()
            client = await self._get_client()
            response = await client.get(
                "/quote",
                params={"symbol": "AAPL", "token": api_key},
            )

            if response.status_code == 200:
                return {
                    "status_code": 200,
                    "success": True,
                    "message": "Finnhub API key valid",
                    "details": {"endpoint": "/quote", "symbol": "AAPL"},
                }
            if response.status_code in (401, 403):
                return {
                    "status_code": 401,
                    "success": False,
                    "message": "Invalid Finnhub API key",
                    "details": {"status_code": response.status_code, "response": response.text[:500]},
                }

            return {
                "status_code": 503,
                "success": False,
                "message": "Finnhub service unavailable",
                "details": {"status_code": response.status_code, "response": response.text[:500]},
            }
        except httpx.TimeoutException as exc:
            return {
                "status_code": 503,
                "success": False,
                "message": "Finnhub service unavailable",
                "details": {"error": str(exc), "reason": "timeout"},
            }
        except Exception as exc:
            return {
                "status_code": 503,
                "success": False,
                "message": "Finnhub service unavailable",
                "details": {"error": str(exc)},
            }

    async def get_company_news(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
        limit: int = 20,
        offset: int = 0,
        language: str = "en",
        category: str | None = None
    ) -> list[NewsArticle]:
        """Get company news from Finnhub.

        Args:
            symbol: Stock symbol (e.g., 'AAPL')
            from_date: Start date for news search
            to_date: End date for news search
            limit: Number of articles to return (max 100)
            offset: Number of articles to skip
            language: Language filter (default: 'en')
            category: Category filter (earnings, product, merger, legal)

        Returns:
            List of NewsArticle objects

        Raises:
            DataNotFoundError: Symbol not found
            ProviderError: API error or rate limit exceeded
        """
        try:
            # Rate limit check
            if not await self._check_rate_limit():
                error_msg = "Finnhub rate limit exceeded (60/min)"
                if settings.FINNHUB_FALLBACK_ON_RATE_LIMIT:
                    logger.warning(f"{error_msg} - using fallback strategy")
                    raise ProviderError(error_msg)
                else:
                    # Return 429 error
                    raise ProviderError(error_msg)

            # Get API key
            api_key = await self._ensure_api_key()

            # Get HTTP client
            client = await self._get_client()

            # Validate limit
            limit = min(max(limit, 1), 100)

            # Make API request
            logger.debug(
                f"Fetching Finnhub news for {symbol} "
                f"from {from_date.isoformat()} to {to_date.isoformat()}"
            )

            response = await client.get(
                "/company-news",
                params={
                    "symbol": symbol.upper(),
                    "from": from_date.isoformat(),
                    "to": to_date.isoformat(),
                    "token": api_key
                }
            )

            # Handle response
            if response.status_code == 404:
                raise DataNotFoundError("Symbol", symbol)
            elif response.status_code == 429:
                raise ProviderError(
                    "Finnhub rate limit exceeded",
                    details={"status_code": 429, "retry_after": response.headers.get("Retry-After")}
                )
            elif response.status_code != 200:
                raise ProviderError(
                    f"Finnhub API error: {response.status_code}",
                    details={"status_code": response.status_code, "response": response.text}
                )

            # Parse response
            data = response.json()
            if not isinstance(data, list):
                logger.warning(f"Unexpected Finnhub response type: {type(data)}")
                return []

            # Convert to NewsArticle list
            articles = []
            for idx, item in enumerate(data):
                try:
                    # Extract fields
                    article_id = f"finnhub:{item.get('id', f'{symbol}_{idx}')}"
                    headline = item.get("headline", "")
                    summary = item.get("summary", "")
                    image = item.get("image", "")
                    source = item.get("source", "Finnhub")
                    url = item.get("url", "")
                    datetime_ts = item.get("datetime", None)

                    # Parse timestamp
                    if isinstance(datetime_ts, int):
                        published_at = datetime.fromtimestamp(datetime_ts, tz=UTC)
                    else:
                        published_at = datetime.now(UTC)

                    # Parse sentiment
                    sentiment = self._parse_sentiment(item.get("sentiment", {}))

                    # Detect category
                    detected_category = self._detect_category(headline, summary, sentiment)

                    # Apply category filter
                    if category and detected_category != category:
                        continue

                    # Create article
                    articles.append(NewsArticle(
                        article_id=article_id,
                        title=headline,
                        summary=summary,
                        published_at=published_at,
                        source=source,
                        url=url,
                        full_text=None,  # Finnhub doesn't provide full text
                        category=detected_category,
                        # Extra fields
                        image=image,
                        sentiment=sentiment
                    ))

                except Exception as e:
                    logger.warning(f"Failed to parse article {idx}: {e}")
                    continue

            # Apply pagination manually (Finnhub doesn't support limit/offset directly)
            if offset > 0:
                articles = articles[offset:]
            articles = articles[:limit]

            logger.info(f"Retrieved {len(articles)} articles for {symbol} from Finnhub")
            return articles

        except DataNotFoundError:
            raise
        except ProviderError:
            raise
        except httpx.TimeoutException:
            raise ProviderConnectionError(
                f"Finnhub request timeout after {settings.PROVIDER_REQUEST_TIMEOUT}s",
                details={"symbol": symbol}
            )
        except Exception as e:
            logger.error(f"Finnhub error for {symbol}: {e}")
            raise ProviderError(
                f"Failed to fetch news from Finnhub: {e!s}",
                details={"symbol": symbol, "error_type": type(e).__name__}
            )

    # ========================================================================
    # Cleanup
    # ========================================================================

    async def __aenter__(self) -> "FinnhubProvider":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self._close_client()

    def __del__(self) -> None:
        """Cleanup on deletion."""
        try:
            if self._client is not None:
                asyncio.create_task(self._close_client())
        except Exception:
            pass
