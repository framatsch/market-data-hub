#!/usr/bin/env python3
"""Test to show what data is available with current IBKR subscription."""

import asyncio
import sys
import os
import logging

sys.path.append(os.getcwd())

# Suppress logs
logging.getLogger("ib_async").setLevel(logging.CRITICAL)
logging.getLogger("ib_async.wrapper").setLevel(logging.CRITICAL)
logging.getLogger("market_data_hub").setLevel(logging.CRITICAL)

from app.providers.ibkr import IBKRProvider
from datetime import date

async def main():
    print("\n" + "="*70)
    print("IBKR Subscription Analysis - Data Availability")
    print("="*70 + "\n")

    provider = IBKRProvider()

    # Get stock price
    print("📈 STOCK DATA")
    print("-" * 70)
    quote = await provider.get_last_price("AAPL")
    print(f"Symbol:        {quote.symbol}")
    print(f"Price:         ${quote.price:.2f}  ✅ AVAILABLE")
    print(f"Bid:           {quote.bid if quote.bid and quote.bid != -1 else '❌ NOT AVAILABLE'}")
    print(f"Ask:           {quote.ask if quote.ask and quote.ask != -1 else '❌ NOT AVAILABLE'}")
    print(f"Volume:        {quote.volume}")

    # Get option chain
    print("\n\n📊 OPTION DATA")
    print("-" * 70)
    chain = await provider.get_option_chain(
        "AAPL",
        date(2026, 1, 16),
        min_strike=273,
        max_strike=276
    )

    if chain.options:
        opt = chain.options[0]
        print(f"Symbol:        {opt.symbol}")
        print(f"Strike:        ${opt.strike}")
        print(f"Price (Last):  ${opt.price:.2f}  ✅ AVAILABLE")
        print(f"Bid/Ask:       {opt.bid if opt.bid and opt.bid != -1 else '❌ NOT AVAILABLE'} / {opt.ask if opt.ask and opt.ask != -1 else '❌ NOT AVAILABLE'}")

        print(f"\n📈 GREEKS (Level 2 Data)")
        print(f"   IV:         {opt.implied_volatility if opt.implied_volatility else '❌'}")
        print(f"   Delta:      {opt.delta if opt.delta else '❌'}")
        print(f"   Gamma:      {opt.gamma if opt.gamma else '❌'}")
        print(f"   Vega:       {opt.vega if opt.vega else '❌'}")
        print(f"   Theta:      {opt.theta if opt.theta else '❌'}")

    # Summary
    print("\n" + "="*70)
    print("SUMMARY - What You Have:")
    print("="*70)
    print("✅ INCLUDED (Delayed Data Type 3 - FREE):")
    print("   • Stock Close/Last prices")
    print("   • Option Close/Last prices")
    print("   • Greeks (IV, Delta, Gamma, Vega, Theta) from modelGreeks")
    print("   • 15-20 minute delay")
    print()
    print("❌ NOT INCLUDED (Requires PAID Subscription):")
    print("   • Stock Bid/Ask (Real-Time or TOP)")
    print("   • Option Bid/Ask (Real-Time or TOP)")
    print()
    print("COST ESTIMATE:")
    print("   • Stock Top of Book: ~$10/month")
    print("   • Options Top of Book: ~$15/month")
    print()
    print("="*70 + "\n")

if __name__ == "__main__":
    asyncio.run(main())
