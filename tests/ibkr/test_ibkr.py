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

import asyncio
import logging
import os
import sys
from datetime import date, datetime, timedelta

import pytest

# Adjust path so we can import app
sys.path.append(os.getcwd())

from app.config import settings
from app.providers.ibkr import IBKRProvider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_ibkr")

@pytest.mark.asyncio
async def test_ibkr_integration():
    print("--- Starting IBKR Integration Test ---")
    print(f"Connecting to {settings.IBKR_HOST}:{settings.IBKR_PORT} ClientID: {settings.IBKR_CLIENT_ID}")

    provider = IBKRProvider()

    # 1. Test Connection & Historical Data
    print("\n[1] Testing Historical Prices (AAPL)...")
    try:
        end = datetime.now()
        start = end - timedelta(days=30)
        bars = await provider.get_historical_prices("AAPL", "1d", start, end)
        print(f"Got {len(bars)} bars.")
        if bars:
            print(f"Sample bar: {bars[0]}")
        else:
            print("WARNING: No bars returned.")
    except Exception as e:
        print(f"ERROR getting historical prices: {e}")

    # 2. Test Last Price
    print("\n[2] Testing Last Price (AAPL)...")
    try:
        quote = await provider.get_last_price("AAPL")
        print(f"Quote: {quote}")
    except Exception as e:
        print(f"ERROR getting last price: {e}")

    # 3. Test Option Chain
    print("\n[3] Testing Option Chain (AAPL, +30 days approx)...")
    try:
        # Find next valid expiry? Just try one.
        # Ideally we'd scan for one, but provider takes specific date.
        # Let's just try to call it and see if it fails gracefully or finds something
        # if we pick a likely date.
        # Actually, let's use a very specific test if we can, or just expect it to fail if date invalid.
        # But this is an integration test, manual intervention might be needed to pick a valid date.
        expiry = date(2026, 1, 16) # Hardcoded valid expiry from logs
        print(f"Requesting chain for expiry {expiry}")

        # Get narrow range around current price for better data
        chain = await provider.get_option_chain("AAPL", expiry, min_strike=270, max_strike=290)
        print(f"Got {len(chain.options)} options (Strike range 270-290).")

        # Test Filters
        print("\n[3b] Testing Option Chain Filters...")
        # Filter for Calls only in ATM range
        chain_calls = await provider.get_option_chain("AAPL", expiry, min_strike=275, max_strike=285, right="call")
        print(f"Got {len(chain_calls.options)} CALL options (ATM range).")
        if any(o.type != "call" for o in chain_calls.options):
            print("ERROR: Found non-call options in filtered result!")

        # Filter for Strikes > 200
        chain_strikes = await provider.get_option_chain("AAPL", expiry, min_strike=200, max_strike=280)
        print(f"Got {len(chain_strikes.options)} options with strike 200-280.")
        if any(o.strike < 200 for o in chain_strikes.options):
             print("ERROR: Found strike < 200 in filtered result!")

        # Test Level 2 (with graceful fallback)
        print("\n[3c] Testing Option Chain with Level 2 (should fallback if no subscription)...")
        chain_l2 = await provider.get_option_chain("AAPL", expiry, include_level2=True)
        print(f"Got {len(chain_l2.options)} options (Level 2 or Level 1 fallback).")
        print(f"Subscription errors logged: {len(provider._subscription_errors)}")
        if provider._subscription_errors:
            print(f"Error details: {provider._subscription_errors[-1]}")

        if chain.options:
            print(f"Sample option: {chain.options[0]}")

            # 4. Test specific option quote
            print("\n[4] Testing Specific Option Quote...")
            opt = chain.options[0]
            # Use local symbol or constructed ID
            quote = await provider.get_option_quote("AAPL", opt.symbol)
            print(f"Option Quote: {quote}")

            # 4b. Test option quote with Level 2
            print("\n[4b] Testing Option Quote with Level 2...")
            quote_l2 = await provider.get_option_quote("AAPL", opt.symbol, include_level2=True)
            print(f"Option Quote (L2 or fallback): {quote_l2}")

    except Exception as e:
        print(f"ERROR getting option chain (might be invalid date): {e}")

    print("\n--- Test Finished ---")

if __name__ == "__main__":
    try:
        asyncio.run(test_ibkr_integration())
    except KeyboardInterrupt:
        print("Interrupted")
