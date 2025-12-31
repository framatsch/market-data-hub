import sys
sys.path.insert(0, '.')
import asyncio
from datetime import datetime, timedelta, timezone
from app.providers.lseg import LSEGProvider

async def test():
    provider = LSEGProvider()
    try:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=30)

        bars = await provider.get_historical_prices("AAPL", "1d", start, end)
        print("✅ get_historical_prices('AAPL', '1d', 30 days):")
        print(f"   Bars returned: {len(bars)}")
        if bars:
            print("\n   First bar:")
            print(f"     {bars[0]}")
            print("\n   Last bar:")
            print(f"     {bars[-1]}")
        else:
            print("   ERROR: Empty result!")
        return True
    except Exception as e:
        print(f"❌ Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False

result = asyncio.run(test())
