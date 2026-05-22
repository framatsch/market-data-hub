# market-data-hub - FastAPI data service for market and company data
# Copyright (C) 2026  Market Data Hub Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

#!/usr/bin/env python3
"""Test script to verify Greeks extraction from IBKR options."""

import asyncio
import sys
import os
from datetime import date
import logging

sys.path.append(os.getcwd())

# Suppress all IBKR debug output
logging.getLogger("ib_async").setLevel(logging.CRITICAL)
logging.getLogger("ib_async.wrapper").setLevel(logging.CRITICAL)
logging.getLogger("market_data_hub").setLevel(logging.CRITICAL)

from app.providers.ibkr import IBKRProvider

async def main():
    print("\n" + "="*70)
    print("AAPL Option Greeks Test - Delayed Market Data (Type 3)")
    print("="*70 + "\n")

    provider = IBKRProvider()

    # Get current price
    print("📈 Getting current AAPL price...")
    quote = await provider.get_last_price("AAPL")
    current_price = float(quote.price)
    print(f"   Current Price: ${current_price:.2f}\n")

    # Get ATM options without Level 2 first
    print("📊 Test 1: Getting ATM options WITHOUT Level 2 (Delayed Data)")
    print("-" * 70)

    min_strike = int(current_price - 2)
    max_strike = int(current_price + 2)

    chain = await provider.get_option_chain(
        "AAPL",
        date(2026, 1, 16),
        min_strike=min_strike,
        max_strike=max_strike,
        include_level2=False  # Delayed data
    )

    if chain.options:
        atm_call = min([o for o in chain.options if o.type == "call"],
                      key=lambda x: abs(float(x.strike) - current_price))

        print(f"\nATM Call (Strike ${atm_call.strike}):")
        print(f"   Price:              ${atm_call.price:.2f}")
        print(f"   Bid/Ask:            ${atm_call.bid if atm_call.bid else 'N/A'} / ${atm_call.ask if atm_call.ask else 'N/A'}")
        print(f"   Implied Vol (IV):   {atm_call.implied_volatility if atm_call.implied_volatility else 'N/A'}")
        print(f"   Delta:              {atm_call.delta if atm_call.delta else 'N/A'}")
        print(f"   Gamma:              {atm_call.gamma if atm_call.gamma else 'N/A'}")
        print(f"   Vega:               {atm_call.vega if atm_call.vega else 'N/A'}")
        print(f"   Theta:              {atm_call.theta if atm_call.theta else 'N/A'}")

    # Now with Level 2
    print("\n📊 Test 2: Getting ATM options WITH Level 2 (Live Data)")
    print("-" * 70)

    chain_l2 = await provider.get_option_chain(
        "AAPL",
        date(2026, 1, 16),
        min_strike=min_strike,
        max_strike=max_strike,
        include_level2=True  # Live data for Greeks
    )

    if chain_l2.options:
        atm_call_l2 = min([o for o in chain_l2.options if o.type == "call"],
                         key=lambda x: abs(float(x.strike) - current_price))

        print(f"\nATM Call (Strike ${atm_call_l2.strike}):")
        print(f"   Price:              ${atm_call_l2.price:.2f}")
        print(f"   Bid/Ask:            ${atm_call_l2.bid if atm_call_l2.bid else 'N/A'} / ${atm_call_l2.ask if atm_call_l2.ask else 'N/A'}")
        print(f"   Implied Vol (IV):   {atm_call_l2.implied_volatility if atm_call_l2.implied_volatility else 'N/A'}")
        print(f"   Delta:              {atm_call_l2.delta if atm_call_l2.delta else 'N/A'}")
        print(f"   Gamma:              {atm_call_l2.gamma if atm_call_l2.gamma else 'N/A'}")
        print(f"   Vega:               {atm_call_l2.vega if atm_call_l2.vega else 'N/A'}")
        print(f"   Theta:              {atm_call_l2.theta if atm_call_l2.theta else 'N/A'}")

        # Compare
        print("\n" + "="*70)
        if atm_call_l2.delta is not None:
            print("✅ SUCCESS: Greeks ARE now available!")
            if atm_call.delta is None and atm_call_l2.delta is not None:
                print("   → Level 2 provides better Greek data than Level 1")
        else:
            print("⚠️  Greeks still not available - check IBKR subscription/data type")

    print("\n" + "="*70 + "\n")

if __name__ == "__main__":
    asyncio.run(main())
