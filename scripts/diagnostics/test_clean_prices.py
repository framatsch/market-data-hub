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
