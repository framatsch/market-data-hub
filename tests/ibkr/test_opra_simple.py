#!/usr/bin/env python3
"""Test OPRA subscription - simpler approach with single connection."""

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

async def main():
    print("\n" + "="*70)
    print("OPRA Subscription Test - Check Bid/Ask Availability")
    print("="*70)
    print("\nYour subscription: OPRA (US Options Exchanges)")
    print("Expected: Top of Book (Bid/Ask) for US options\n")

    ib = IB()

    try:
        await ib.connectAsync(settings.IBKR_HOST, settings.IBKR_PORT, settings.IBKR_CLIENT_ID)
        print(f"✅ Connected to IBKR at {settings.IBKR_HOST}:{settings.IBKR_PORT}\n")

        # Test Type 1 (LIVE) - should work with OPRA
        print("Testing Type 1 (LIVE) - This is what you need for OPRA:")
        print("-" * 70)
        ib.reqMarketDataType(1)
        await asyncio.sleep(0.5)

        # Test Stock
        print("\n📈 Stock (AAPL) - Live data:")
        stock = Stock("AAPL", "SMART", "USD")
        qualified = await ib.qualifyContractsAsync(stock)
        if qualified:
            stock = qualified[0]
            ticker = ib.reqMktData(stock, "", False, False)
            await asyncio.sleep(3)

            print(f"  Last:  {ticker.last if ticker.last and not math.isnan(ticker.last) else f'N/A (close: {ticker.close})'}")
            print(f"  Bid:   {f'✅ ${ticker.bid:.2f}' if ticker.bid and ticker.bid != -1 and ticker.bid > 0 else f'❌ N/A (got: {ticker.bid})'}")
            print(f"  Ask:   {f'✅ ${ticker.ask:.2f}' if ticker.ask and ticker.ask != -1 and ticker.ask > 0 else f'❌ N/A (got: {ticker.ask})'}")

            ib.cancelMktData(stock)

        # Test Option - THIS is what OPRA should enable
        print("\n📊 Option (AAPL Call 275, Jan 2026) - With OPRA subscription:")
        opt = Option("AAPL", "20260116", 275, "C", "SMART")
        qualified = await ib.qualifyContractsAsync(opt)
        if qualified:
            opt = qualified[0]
            # Request with "106" for options Level 2 Greeks
            ticker = ib.reqMktData(opt, "106", False, False)
            await asyncio.sleep(4)

            has_bid = ticker.bid and ticker.bid != -1 and ticker.bid > 0
            has_ask = ticker.ask and ticker.ask != -1 and ticker.ask > 0

            price_val = ticker.last if ticker.last and not math.isnan(ticker.last) else ticker.close
            print(f"  Price: {f'✅ ${price_val:.2f}' if price_val else 'N/A'}")
            print(f"  Bid:   {f'✅ ${ticker.bid:.2f}' if has_bid else f'❌ N/A (got: {ticker.bid})'}")
            print(f"  Ask:   {f'✅ ${ticker.ask:.2f}' if has_ask else f'❌ N/A (got: {ticker.ask})'}")
            print(f"  IV:    {ticker.modelGreeks.impliedVol if ticker.modelGreeks else 'N/A'}")

            ib.cancelMktData(opt)

        # Summary
        print("\n" + "="*70)
        print("SUMMARY - What should happen with OPRA:")
        print("="*70)
        print("""
✅ OPRA enables:
   • Top of Book (Bid/Ask) for US options
   • Real-time quotes with Type 1 (LIVE)
   • Greeks (Level 2 data)

IF you DON'T see Bid/Ask above:

   1. Check in TWS:
      Account → Settings → Market Data Subscriptions

   2. Verify OPRA shows:
      ✅ "Activated" OR "Waived (commissions)"

   3. Check API permissions:
      Account → Settings → API → Market Data API
      → Make sure "Market Data" is enabled

   4. If still not working:
      • Restart TWS/Gateway
      • Reconnect your API client

RECOMMENDED CONFIG:
   • IBKR_MARKET_DATA_TYPE = 1  (for OPRA with Bid/Ask)
   • IBKR_MARKET_DATA_TYPE = 3  (for free delayed data, no Bid/Ask)
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
    asyncio.run(main())
