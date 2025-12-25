#!/usr/bin/env python3
"""Clean test for AAPL ATM option prices with suppressed warnings."""

import asyncio
import sys
import os
import logging

sys.path.append(os.getcwd())

# Suppress all IBKR debug output
logging.getLogger("ib_async").setLevel(logging.CRITICAL)
logging.getLogger("ib_async.wrapper").setLevel(logging.CRITICAL)
logging.getLogger("market_data_hub").setLevel(logging.CRITICAL)

from app.providers.ibkr import IBKRProvider

async def main():
    print("\n" + "="*60)
    print("AAPL ATM Option Prices - Real-Time Test")
    print("="*60 + "\n")

    provider = IBKRProvider()

    # Get current price
    print("📈 Getting current AAPL price...")
    quote = await provider.get_last_price("AAPL")
    current_price = float(quote.price)
    print(f"   Current Price: ${current_price:.2f}\n")

    # Get ATM options
    print("📊 Getting ATM option chain (Jan 16, 2026)...")
    from datetime import date

    min_strike = int(current_price - 2)
    max_strike = int(current_price + 2)

    chain = await provider.get_option_chain(
        "AAPL",
        date(2026, 1, 16),
        min_strike=min_strike,
        max_strike=max_strike,
        include_level2=False
    )

    if not chain.options:
        print("   ❌ No options found")
        return

    print(f"   Found {len(chain.options)} options\n")

    # Find ATM calls and puts
    calls = [o for o in chain.options if o.type == "call"]
    puts = [o for o in chain.options if o.type == "put"]

    print("   CALLS:")
    print("   " + "-"*50)
    for opt in sorted(calls, key=lambda x: float(x.strike)):
        price_str = f"${opt.price:.2f}" if opt.price else "N/A"
        print(f"   Strike ${opt.strike:>7.1f}  |  Price: {price_str:>8}")

    print("\n   PUTS:")
    print("   " + "-"*50)
    for opt in sorted(puts, key=lambda x: float(x.strike)):
        price_str = f"${opt.price:.2f}" if opt.price else "N/A"
        print(f"   Strike ${opt.strike:>7.1f}  |  Price: {price_str:>8}")

    print("\n" + "="*60)
    print("✅ Data retrieved successfully (Delayed Market Data, Type 3)")
    print("="*60 + "\n")

if __name__ == "__main__":
    asyncio.run(main())
