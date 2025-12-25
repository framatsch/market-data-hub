#!/usr/bin/env python3
"""Test Type 2 (FROZEN) with OPRA subscription."""

import asyncio
import sys
import os
import logging
import math

sys.path.append(os.getcwd())

# Suppress logs
logging.getLogger("ib_async").setLevel(logging.CRITICAL)
logging.getLogger("ib_async.wrapper").setLevel(logging.CRITICAL)

from ib_async import IB, Stock, Option
from app.config import settings

async def test_frozen_data():
    print("\n" + "="*70)
    print("Testing Type 2 (FROZEN) Data with OPRA Subscription")
    print("="*70)
    print("\nType 2 = Last known Bid/Ask values (frozen quotes)")
    print("Expected: If OPRA works, should show Bid/Ask from last update\n")

    ib = IB()

    try:
        await ib.connectAsync(settings.IBKR_HOST, settings.IBKR_PORT, settings.IBKR_CLIENT_ID)
        print(f"✅ Connected to IBKR\n")

        # Set to Type 2 (FROZEN)
        print("Setting Market Data Type to 2 (FROZEN)...")
        ib.reqMarketDataType(2)
        await asyncio.sleep(0.5)

        # Test Stock with Type 2
        print("\n" + "-"*70)
        print("📈 Stock (AAPL) - Type 2 (FROZEN)")
        print("-"*70)
        stock = Stock("AAPL", "SMART", "USD")
        qualified = await ib.qualifyContractsAsync(stock)
        if qualified:
            stock = qualified[0]
            ticker = ib.reqMktData(stock, "", False, False)
            await asyncio.sleep(3)

            def format_value(val, label=""):
                if val is None:
                    return f"❌ None"
                if isinstance(val, float) and math.isnan(val):
                    return f"❌ NaN"
                if val == -1:
                    return f"❌ Not available"
                if val > 0:
                    return f"✅ ${val:.2f}"
                return f"? {val}"

            print(f"  Last:   {format_value(ticker.last)}")
            print(f"  Close:  {format_value(ticker.close)}")
            print(f"  Bid:    {format_value(ticker.bid)}")
            print(f"  Ask:    {format_value(ticker.ask)}")
            print(f"  Time:   {ticker.time}")

            ib.cancelMktData(stock)

        # Test Option with Type 2 - THIS is what matters for OPRA
        print("\n" + "-"*70)
        print("📊 Option (AAPL Call 275, Jan 2026) - Type 2 (FROZEN) + OPRA")
        print("-"*70)
        opt = Option("AAPL", "20260116", 275, "C", "SMART")
        qualified = await ib.qualifyContractsAsync(opt)
        if qualified:
            opt = qualified[0]
            # Request with "106" for Greeks
            ticker = ib.reqMktData(opt, "106", False, False)
            await asyncio.sleep(4)

            def format_value(val, label=""):
                if val is None:
                    return f"❌ None"
                if isinstance(val, float) and math.isnan(val):
                    return f"❌ NaN"
                if val == -1:
                    return f"❌ Not available"
                if val > 0:
                    return f"✅ ${val:.2f}"
                return f"? {val}"

            print(f"  Last:   {format_value(ticker.last)}")
            print(f"  Close:  {format_value(ticker.close)}")
            print(f"  Bid:    {format_value(ticker.bid)}")
            print(f"  Ask:    {format_value(ticker.ask)}")
            print(f"  Time:   {ticker.time}")

            if ticker.modelGreeks:
                mg = ticker.modelGreeks
                print(f"\n  Greeks available:")
                print(f"    IV:    {mg.impliedVol if mg.impliedVol else 'N/A'}")
                print(f"    Delta: {mg.delta if mg.delta else 'N/A'}")
            else:
                print(f"\n  Greeks: ❌ Not available")

            ib.cancelMktData(opt)

        # Summary
        print("\n" + "="*70)
        print("RESULT:")
        print("="*70)
        print("""
Type 2 (FROZEN) with OPRA:
- Shows "frozen" Bid/Ask (last known value)
- Good for checking if OPRA is working
- Slower updates (only when market changes)

If you see Bid/Ask above → OPRA IS WORKING! ✅
If you DON'T see Bid/Ask → Try these options:

1. Type 1 (LIVE): IBKR_MARKET_DATA_TYPE=1
2. Type 3 (DELAYED): IBKR_MARKET_DATA_TYPE=3 (free, no OPRA needed)
3. Type 4 (DELAYED FROZEN): IBKR_MARKET_DATA_TYPE=4

Next steps based on results above...
        """)
        print("="*70 + "\n")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if ib.isConnected():
            ib.disconnect()

if __name__ == "__main__":
    asyncio.run(test_frozen_data())
