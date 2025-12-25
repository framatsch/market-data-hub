#!/usr/bin/env python3
"""Test script to check if we can get ATM option prices for AAPL with Level 2 data."""

import asyncio
import sys
import os
from datetime import date, timedelta
import logging
import io

sys.path.append(os.getcwd())

# Suppress all IBKR debug logs for clean output
logging.getLogger("ib_async").setLevel(logging.CRITICAL)
logging.getLogger("ib_async.wrapper").setLevel(logging.CRITICAL)
logging.getLogger("market_data_hub").setLevel(logging.ERROR)

from app.providers.ibkr import IBKRProvider
from app.config import settings

async def test_atm_option():
    print("=== Testing ATM Option for AAPL ===\n")

    provider = IBKRProvider()

    # Step 1: Get current AAPL price
    print("Step 1: Getting current AAPL price...")
    try:
        quote = await provider.get_last_price("AAPL")
        current_price = float(quote.price)
        print(f"✅ Current AAPL price: ${current_price:.2f}\n")
    except Exception as e:
        print(f"❌ Error getting AAPL price: {e}")
        return

    # Step 2: Get option chain for near-term expiry
    print("Step 2: Getting option chain for January 2026...")
    try:
        expiry = date(2026, 1, 16)

        # Get options near current price (ATM ±5)
        min_strike = int(current_price - 5)
        max_strike = int(current_price + 5)

        print(f"Searching for strikes between ${min_strike} and ${max_strike}")

        # Try without Level 2 first
        print("\nTrying WITHOUT Level 2 data:")
        chain = await provider.get_option_chain(
            "AAPL",
            expiry,
            min_strike=min_strike,
            max_strike=max_strike,
            include_level2=False
        )

        if chain.options:
            print(f"✅ Found {len(chain.options)} options")
            # Find closest to current price
            atm_call = min([o for o in chain.options if o.type == "call"],
                          key=lambda x: abs(float(x.strike) - current_price))

            print(f"\n📊 Closest ATM Call Option:")
            print(f"   Symbol: {atm_call.symbol}")
            print(f"   Strike: ${atm_call.strike}")
            print(f"   Price: ${atm_call.price if atm_call.price else 'N/A'}")
            print(f"   Bid: ${atm_call.bid if atm_call.bid else 'N/A'}")
            print(f"   Ask: ${atm_call.ask if atm_call.ask else 'N/A'}")
            print(f"   IV: {atm_call.implied_volatility if atm_call.implied_volatility else 'N/A'}")
            print(f"   Delta: {atm_call.delta if atm_call.delta else 'N/A'}")

            # Now try WITH Level 2
            print("\n" + "="*50)
            print("Trying WITH Level 2 data:")
            chain_l2 = await provider.get_option_chain(
                "AAPL",
                expiry,
                min_strike=min_strike,
                max_strike=max_strike,
                include_level2=True
            )

            if chain_l2.options:
                atm_call_l2 = min([o for o in chain_l2.options if o.type == "call"],
                                 key=lambda x: abs(float(x.strike) - current_price))

                print(f"\n📊 ATM Call Option WITH Level 2:")
                print(f"   Symbol: {atm_call_l2.symbol}")
                print(f"   Strike: ${atm_call_l2.strike}")
                print(f"   Price: ${atm_call_l2.price if atm_call_l2.price else 'N/A'}")
                print(f"   Bid: ${atm_call_l2.bid if atm_call_l2.bid else 'N/A'}")
                print(f"   Ask: ${atm_call_l2.ask if atm_call_l2.ask else 'N/A'}")
                print(f"   IV: {atm_call_l2.implied_volatility if atm_call_l2.implied_volatility else 'N/A'}")
                print(f"   Delta: {atm_call_l2.delta if atm_call_l2.delta else 'N/A'}")
                print(f"   Gamma: {atm_call_l2.gamma if atm_call_l2.gamma else 'N/A'}")
                print(f"   Theta: {atm_call_l2.theta if atm_call_l2.theta else 'N/A'}")
                print(f"   Vega: {atm_call_l2.vega if atm_call_l2.vega else 'N/A'}")

                # Compare
                print("\n" + "="*50)
                if atm_call_l2.delta is not None:
                    print("✅ Level 2 data (Greeks) ARE available!")
                else:
                    print("⚠️  Level 2 data (Greeks) NOT available - check subscription")

                if atm_call_l2.bid is not None and atm_call.bid is None:
                    print("✅ Level 2 provides better bid/ask data")

        else:
            print("❌ No options found in the specified range")

    except Exception as e:
        print(f"❌ Error getting option chain: {e}")
        import traceback
        traceback.print_exc()

    print("\n=== Test Complete ===")

if __name__ == "__main__":
    asyncio.run(test_atm_option())
