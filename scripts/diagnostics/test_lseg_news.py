#!/usr/bin/env python3
"""
Test LSEG News API - Direct test of rd.news.get_headlines()
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Load .env file
env_path = project_root / ".env"
load_dotenv(env_path)

print(f"Loading .env from: {env_path}")
print(f"LSEG_APP_KEY: {os.getenv('LSEG_APP_KEY', 'NOT SET')[:20]}...")
print(f"LSEG_USERNAME: {os.getenv('LSEG_USERNAME', 'NOT SET')}")
print()

try:
    import refinitiv.data as rd
    print("✅ refinitiv.data imported successfully")
except ImportError as e:
    print(f"❌ Failed to import refinitiv.data: {e}")
    sys.exit(1)

# Create session
try:
    print("\n📡 Creating LSEG session...")
    session = rd.session.platform.Definition(
        app_key=os.getenv("LSEG_APP_KEY"),
        grant=rd.session.platform.GrantPassword(
            username=os.getenv("LSEG_USERNAME"),
            password=os.getenv("LSEG_PASSWORD")
        ),
        signon_control=True
    ).get_session()

    print("Opening session...")
    session.open()

    print("Setting default session...")
    rd.session.set_default(session)

    print("✅ Session created successfully\n")

except Exception as e:
    print(f"❌ Session creation failed: {e}")
    sys.exit(1)

# Test news API
try:
    print("📰 Fetching news headlines for IBM.N...")
    print("Query: 'R:IBM.N AND Language:LEN'")
    print("Start date: 2025-04-04")
    print("Count: 150\n")

    from refinitiv.data.content import news

    response = news.headlines.Definition(query="Google", count=5).get_data()

    df = response.data.df

    # df = rd.news.get_headlines(
    #     'R:IBM.N AND Language:LEN',
    #     start='2025-04-04',
    #     count=150
    # )

    if df is None or df.empty:
        print("⚠️  No news articles found")
    else:
        print(f"✅ Retrieved {len(df)} news articles\n")
        print("=" * 80)
        print("FIRST 5 HEADLINES:")
        print("=" * 80)
        print(df.head())
        print("\n" + "=" * 80)
        print(f"COLUMNS: {list(df.columns)}")
        print("=" * 80)

        # Save to CSV for inspection
        output_file = project_root / "scripts" / "diagnostics" / "lseg_news_output.csv"
        df.to_csv(output_file)
        print(f"\n💾 Full results saved to: {output_file}")

except Exception as e:
    print(f"❌ News API call failed: {e}")
    print(f"Error type: {type(e).__name__}")
    import traceback
    print("\nFull traceback:")
    traceback.print_exc()
    sys.exit(1)

print("\n✅ Test completed successfully!")
