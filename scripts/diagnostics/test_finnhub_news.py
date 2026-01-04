#!/usr/bin/env python3
"""
Test Finnhub News Provider - Direct test of company news endpoint
"""

import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime, date, timezone, timedelta
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Load .env file
env_path = project_root / ".env"
load_dotenv(env_path)

print(f"Loading .env from: {env_path}")
print(f"FINNHUB_API_KEY: {os.getenv('FINNHUB_API_KEY', 'NOT SET')[:20]}...")
print()

# Import after path setup
from app.providers.finnhub import FinnhubProvider
from app.utils.errors import DataNotFoundError, ProviderError


async def main():
    """Test Finnhub provider."""

    try:
        # Initialize provider
        print("🚀 Initializing FinnhubProvider...")
        provider = FinnhubProvider()
        print("✅ Provider initialized\n")

        # Test 1: Get AAPL news (last 30 days)
        print("=" * 80)
        print("TEST 1: Get AAPL news (last 30 days)")
        print("=" * 80)

        to_date = date.today()
        from_date = to_date - timedelta(days=30)

        try:
            articles = await provider.get_company_news(
                symbol="AAPL",
                from_date=from_date,
                to_date=to_date,
                limit=10
            )

            print(f"✅ Retrieved {len(articles)} articles\n")

            for i, article in enumerate(articles[:5], 1):
                print(f"\n{i}. {article.title}")
                print(f"   Source: {article.source}")
                print(f"   Date: {article.published_at.strftime('%Y-%m-%d %H:%M:%S')}")
                if article.category:
                    print(f"   Category: {article.category}")
                if article.sentiment:
                    print(f"   Sentiment: {article.sentiment}")
                print(f"   URL: {article.url}")

        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()

        # Test 2: Rate limiting info
        print("\n" + "=" * 80)
        print("TEST 2: Rate Limiting Info")
        print("=" * 80)

        print(f"Rate Limit: {provider._rate_limit_per_min} calls/min")
        print(f"Requests in current window: {len(provider._request_times)}")
        print(f"Remaining capacity: {provider._rate_limit_per_min - len(provider._request_times)}")

        # Test 3: Category filtering
        print("\n" + "=" * 80)
        print("TEST 3: Category Filtering (earnings only)")
        print("=" * 80)

        try:
            articles = await provider.get_company_news(
                symbol="TSLA",
                from_date=from_date,
                to_date=to_date,
                limit=20,
                category="earnings"
            )

            print(f"✅ Retrieved {len(articles)} articles matching 'earnings'\n")

            for i, article in enumerate(articles[:3], 1):
                print(f"{i}. {article.title}")
                print(f"   Category: {article.category}")

        except Exception as e:
            print(f"❌ Error: {e}")

        # Test 4: Invalid symbol
        print("\n" + "=" * 80)
        print("TEST 4: Invalid Symbol Error Handling")
        print("=" * 80)

        try:
            articles = await provider.get_company_news(
                symbol="INVALID_SYMBOL_XYZ",
                from_date=from_date,
                to_date=to_date
            )

            if not articles:
                print("✅ No articles found (expected for invalid symbol)")
            else:
                print(f"Got {len(articles)} articles")

        except DataNotFoundError as e:
            print(f"✅ DataNotFoundError raised as expected: {e}")
        except Exception as e:
            print(f"❌ Unexpected error: {e}")

        # Test 5: Sentiment analysis
        print("\n" + "=" * 80)
        print("TEST 5: Sentiment Analysis")
        print("=" * 80)

        try:
            articles = await provider.get_company_news(
                symbol="MSFT",
                from_date=from_date,
                to_date=to_date,
                limit=5
            )

            print(f"✅ Retrieved {len(articles)} articles\n")

            for article in articles:
                if article.sentiment:
                    print(f"Title: {article.title[:60]}...")
                    print(f"Sentiment: {article.sentiment}")
                    print()

        except Exception as e:
            print(f"❌ Error: {e}")

        # Cleanup
        await provider._close_client()

        print("\n" + "=" * 80)
        print("✅ All tests completed!")
        print("=" * 80)

    except Exception as e:
        print(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
