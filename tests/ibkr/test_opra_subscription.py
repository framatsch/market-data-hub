#!/usr/bin/env python3
"""Test different MARKET_DATA_TYPE to find which one enables Bid/Ask with OPRA subscription."""

import asyncio
import sys
import os
import logging

sys.path.append(os.getcwd())

# Suppress logs
logging.getLogger("ib_async").setLevel(logging.CRITICAL)
logging.getLogger("ib_async.wrapper").setLevel(logging.CRITICAL)
logging.getLogger("market_data_hub").setLevel(logging.CRITICAL)

from ib_async import IB, Stock, Option
from app.config import settings

async def test_market_data_type(data_type: int, name: str):
    """Test a specific market data type for bid/ask availability."""
    ib = IB()

    try:
        await ib.connectAsync(settings.IBKR_HOST, settings.IBKR_PORT, 900 + data_type)

        # Request market data type
        ib.reqMarketDataType(data_type)
        await asyncio.sleep(0.5)  # Let the type change take effect

        # Test Stock
        print(f"\n  Stock (AAPL):")
        stock = Stock("AAPL", "SMART", "USD")
        qualified = await ib.qualifyContractsAsync(stock)
        if qualified:
            stock = qualified[0]
            ticker = ib.reqMktData(stock, "", False, False)
            await asyncio.sleep(3)  # Longer wait for data

            # Check for valid data (not nan, not -1, not None)
            has_price = ticker.last and not (isinstance(ticker.last, float) and __import__('math').isnan(ticker.last))
            has_bid = ticker.bid and ticker.bid != -1 and ticker.bid > 0
            has_ask = ticker.ask and ticker.ask != -1 and ticker.ask > 0

            bid_status = f"✅ ${ticker.bid:.2f}" if has_bid else f"❌ (got: {ticker.bid})"
            ask_status = f"✅ ${ticker.ask:.2f}" if has_ask else f"❌ (got: {ticker.ask})"
            price_status = f"✅ ${ticker.last:.2f}" if has_price else f"Close: ${ticker.close if ticker.close else 'N/A'}"

            print(f"     Price: {price_status}")
            print(f"     Bid:   {bid_status}")
            print(f"     Ask:   {ask_status}")

            ib.cancelMktData(stock)

        # Test Option
        print(f"\n  Option (AAPL Call 275):")
        opt = Option("AAPL", "20260116", 275, "C", "SMART")
        qualified = await ib.qualifyContractsAsync(opt)
        if qualified:
            opt = qualified[0]
            ticker = ib.reqMktData(opt, "", False, False)
            await asyncio.sleep(3)  # Longer wait for data

            has_price = ticker.last and not (isinstance(ticker.last, float) and __import__('math').isnan(ticker.last))
            has_bid = ticker.bid and ticker.bid != -1 and ticker.bid > 0
            has_ask = ticker.ask and ticker.ask != -1 and ticker.ask > 0

            bid_status = f"✅ ${ticker.bid:.2f}" if has_bid else f"❌ (got: {ticker.bid})"
            ask_status = f"✅ ${ticker.ask:.2f}" if has_ask else f"❌ (got: {ticker.ask})"
            price_status = f"✅ ${ticker.last:.2f}" if has_price else f"Close: ${ticker.close if ticker.close else 'N/A'}"
    except Exception as e:
        print(f"  ❌ Error: {str(e)[:80]}")
        return False
    finally:
        if ib.isConnected():
            ib.disconnect()
            await asyncio.sleep(0.5)


async def main():
    print("\n" + "="*70)
    print("Testing MARKET_DATA_TYPE with OPRA Subscription")
    print("="*70)
    print("\nYour subscription: OPRA (US Options Exchanges)")
    print("Commission waiver: If monthly commissions >= $20 USD\n")

    data_types = [
        (1, "LIVE Data"),
        (2, "FROZEN Data"),
        (3, "DELAYED Data"),
        (4, "DELAYED FROZEN Data"),
    ]

    results = {}

    for dtype, dname in data_types:
        print(f"\n{'='*70}")
        print(f"Type {dtype}: {dname}")
        print(f"{'='*70}")

        success = await test_market_data_type(dtype, dname)
        results[dtype] = success

    # Summary
    print(f"\n\n{'='*70}")
    print("RECOMMENDATION FOR YOUR OPRA SUBSCRIPTION:")
    print(f"{'='*70}")
    print("""
Based on IBKR documentation:
- Type 1 (LIVE): Should give you REAL-TIME Bid/Ask with OPRA ✅
- Type 2 (FROZEN): Frozen quotes (last known value)
- Type 3 (DELAYED): 15-20 min delay, NO Bid/Ask
- Type 4 (DELAYED FROZEN): Combination

→ IF you see Bid/Ask above, your OPRA is working!
→ IF not, check TWS:
   1. Account → Settings → Market Data Subscriptions
   2. Verify OPRA is "Activated" or "Waived"
   3. Check if API has "Market Data" access enabled

NEXT STEPS:
1. Check which Type above shows Bid/Ask data
2. Update IBKR_MARKET_DATA_TYPE in config.py to that value
3. Alternatively, set via environment: IBKR_MARKET_DATA_TYPE=1
    """)
    print(f"{'='*70}\n")

if __name__ == "__main__":
    asyncio.run(main())
