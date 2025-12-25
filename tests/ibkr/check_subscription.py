#!/usr/bin/env python3
"""Check what market data is actually available from IBKR."""

import asyncio
import sys
import os
from datetime import date
import logging

sys.path.append(os.getcwd())

# Suppress all IBKR debug logs for clean output
logging.getLogger("ib_async").setLevel(logging.CRITICAL)
logging.getLogger("ib_async.wrapper").setLevel(logging.CRITICAL)

from ib_async import IB, Stock, Option
from app.config import settings

async def check_subscriptions():
    print("=== Checking IBKR Market Data Subscriptions ===\n")

    ib = IB()

    try:
        await ib.connectAsync(settings.IBKR_HOST, settings.IBKR_PORT, settings.IBKR_CLIENT_ID)
        print(f"✅ Connected to IBKR at {settings.IBKR_HOST}:{settings.IBKR_PORT}\n")

        # Qualify contracts first
        stock = Stock("AAPL", "SMART", "USD")
        qualified_stock = await ib.qualifyContractsAsync(stock)
        if not qualified_stock:
            print("❌ Could not qualify stock contract")
            return
        stock = qualified_stock[0]
        print(f"✅ Qualified stock: {stock}\n")

        # Test 1: Stock with delayed data (should work)
        print("Test 1: Stock with DELAYED data (Type 3)")
        ib.reqMarketDataType(3)  # Delayed
        ticker = ib.reqMktData(stock, "", False, False)
        await asyncio.sleep(3)

        print(f"  Last: {ticker.last}")
        print(f"  Bid: {ticker.bid}")
        print(f"  Ask: {ticker.ask}")
        print(f"  Close: {ticker.close}")

        ib.cancelMktData(stock)

        # Test 2: Stock with live data (may fail)
        print("\nTest 2: Stock with LIVE data (Type 1)")
        ib.reqMarketDataType(1)  # Live
        ticker = ib.reqMktData(stock, "", False, False)
        await asyncio.sleep(3)

        print(f"  Last: {ticker.last}")
        print(f"  Bid: {ticker.bid}")
        print(f"  Ask: {ticker.ask}")
        print(f"  Close: {ticker.close}")

        ib.cancelMktData(stock)

        # Test 3: Option with delayed data
        print("\nTest 3: Option with DELAYED data (Type 3)")
        ib.reqMarketDataType(3)
        option = Option("AAPL", "20260116", 275, "C", "SMART")
        qualified = await ib.qualifyContractsAsync(option)
        if qualified:
            option = qualified[0]
            ticker = ib.reqMktData(option, "", False, False)
            await asyncio.sleep(5)

            print(f"  Last: {ticker.last}")
            print(f"  Bid: {ticker.bid}")
            print(f"  Ask: {ticker.ask}")
            print(f"  Close: {ticker.close}")
            print(f"  Model Greeks: {ticker.modelGreeks}")

            ib.cancelMktData(option)

        # Test 4: Option with live data + Greeks
        print("\nTest 4: Option with LIVE data + Greeks (Type 1)")
        ib.reqMarketDataType(1)
        ticker = ib.reqMktData(option, "106", False, False)  # 106 = Option Greeks
        await asyncio.sleep(5)

        print(f"  Last: {ticker.last}")
        print(f"  Bid: {ticker.bid}")
        print(f"  Ask: {ticker.ask}")
        print(f"  Close: {ticker.close}")
        print(f"  Model Greeks: {ticker.modelGreeks}")

        ib.cancelMktData(option)

        print("\n" + "="*60)
        print("Summary:")
        print("- If you see values above, those data types work")
        print("- If you see 'nan' or None, you need subscription")
        print("- Check TWS: Account → Settings → Market Data Subscriptions")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if ib.isConnected():
            ib.disconnect()

if __name__ == "__main__":
    asyncio.run(check_subscriptions())
