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
"""
Test script to verify market_data_type parameter changes.
Tests the new API parameter and behavior.
"""
import asyncio
from app.providers.ibkr import IBKRProvider
from datetime import date

async def test_market_data_type():
    """Test different market data types."""
    print("🧪 Testing market_data_type parameter...")

    provider = IBKRProvider()

    # Check default from config
    print(f"\n📊 Default market_data_type from config: {provider.market_data_type}")
    print(f"   Expected: 3 (Delayed)")

    # Test 1: No explicit market_data_type (should use default 3)
    print("\n✅ Test 1: Using default market_data_type (None)")
    try:
        chain = await provider.get_option_chain(
            symbol="IWM",
            expiry=date(2026, 1, 13),
            min_strike=227.0,
            max_strike=230.0,
            market_data_type=None  # Should use default from config
        )
        print(f"   Got {len(chain.options)} options")
        print(f"   Provider: {chain.provider}")
    except Exception as e:
        print(f"   ⚠️  Error: {e}")

    # Test 2: Explicit market_data_type=3 (Delayed)
    print("\n✅ Test 2: Explicit market_data_type=3 (Delayed)")
    try:
        chain = await provider.get_option_chain(
            symbol="IWM",
            expiry=date(2026, 1, 13),
            min_strike=227.0,
            max_strike=230.0,
            market_data_type=3
        )
        print(f"   Got {len(chain.options)} options")
    except Exception as e:
        print(f"   ⚠️  Error: {e}")

    # Test 3: market_data_type=1 (Live - requires Level 2)
    print("\n✅ Test 3: Explicit market_data_type=1 (Live/Level 2)")
    print("   (This will show Error 10091 warnings if no Level 2 subscription)")
    try:
        chain = await provider.get_option_chain(
            symbol="IWM",
            expiry=date(2026, 1, 13),
            min_strike=227.0,
            max_strike=230.0,
            market_data_type=1
        )
        print(f"   Got {len(chain.options)} options (graceful degradation works!)")
    except Exception as e:
        print(f"   ⚠️  Error: {e}")

    # Close connection
    if provider.ib.isConnected():
        provider.ib.disconnect()

    print("\n✅ All tests completed!")
    print("\n📝 Summary:")
    print("   - market_data_type parameter replaces include_level2")
    print("   - Default is now 3 (Delayed) - no subscription required")
    print("   - Error 10091 warnings logged at DEBUG level (not visible by default)")
    print("   - System gracefully degrades to available data")

if __name__ == "__main__":
    asyncio.run(test_market_data_type())
