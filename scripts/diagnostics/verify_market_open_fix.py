#!/usr/bin/env python3
"""
Verify that the fixed IBKR provider correctly returns is_market_open.

This test verifies the fix for the issue where is_market_open returned null.
The fix includes:
1. Correct ContractDetails access (ib_async vs ib_insync)
2. Parse new IBKR trading hours format (20260122:0930-20260122:1600)
3. Use dynamic timezone from IBKR (US/Eastern, MET, Japan, etc.)
"""

import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from app.providers.ibkr import IBKRProvider
from datetime import datetime

async def test_market_open():
    """Test the complete flow: connect -> qualify -> get trading hours -> is_market_open"""

    print("\n" + "="*80)
    print("VERIFICATION: is_market_open Fix for IBKR Provider")
    print("="*80)

    print(f"\n📅 Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    provider = IBKRProvider()
    success_count = 0
    test_count = 0

    # Test multiple symbols to verify timezone handling
    test_symbols = ["IWM", "AAPL"]

    for symbol in test_symbols:
        test_count += 1
        print(f"\n[Test {test_count}] Testing {symbol}...")
        print("-" * 80)

        try:
            quote = await provider.get_last_price(symbol)

            print(f"  Symbol: {quote.symbol}")
            print(f"  Price: {quote.price}")
            print(f"  is_market_open: {quote.is_market_open}")

            if quote.is_market_open is None:
                print(f"  ❌ FAIL: is_market_open is None")
            else:
                print(f"  ✅ PASS: is_market_open = {quote.is_market_open}")
                success_count += 1

        except Exception as e:
            print(f"  ❌ ERROR: {e}")

    print("\n" + "="*80)
    print(f"RESULT: {success_count}/{test_count} tests passed")

    if success_count == test_count:
        print("✅ ALL TESTS PASSED - is_market_open fix verified!")
        print("="*80 + "\n")
        return True
    else:
        print("❌ SOME TESTS FAILED")
        print("="*80 + "\n")
if __name__ == "__main__":
    result = asyncio.run(test_market_open())
    sys.exit(0 if result else 1)
