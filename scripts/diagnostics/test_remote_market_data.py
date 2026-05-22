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
Test script for remote IB Gateway with different market data types.
Tests against: ib-gateway.framas.cloud:4002, Client ID 10001

Expected behavior:
- Level 3 (Delayed): ✅ Data + No errors in log
- Level 2 (Frozen):  ✅ Data + No errors in log (if OPRA subscription)
- Level 1 (Live):    ❌ Error 10091 + ProviderError exception
"""
import asyncio
from datetime import date
from app.providers.ibkr import IBKRProvider
from app.utils.errors import ProviderError
from app import config

# Override config for remote gateway
config.settings.IBKR_HOST = "ib-gateway.framas.cloud"
config.settings.IBKR_PORT = 4002
config.settings.IBKR_CLIENT_ID = 10001

async def test_level(level: int, symbol: str = "IWM", expiry_str: str = "2026-01-13"):
    """Test a specific market data level."""
    level_names = {1: "Live", 2: "Frozen", 3: "Delayed"}
    print(f"\n{'='*60}")
    print(f"🧪 Test: market_data_type={level} ({level_names.get(level, 'Unknown')})")
    print(f"{'='*60}")

    provider = IBKRProvider()

    try:
        # Parse expiry
        expiry = date.fromisoformat(expiry_str)

        # Request option chain with specific market data type
        chain = await provider.get_option_chain(
            symbol=symbol,
            expiry=expiry,
            min_strike=227.0,
            max_strike=230.0,
            market_data_type=level
        )

        # Success!
        print(f"✅ SUCCESS")
        print(f"   Got {len(chain.options)} options")
        if chain.options:
            opt = chain.options[0]
            print(f"   Sample: {opt.symbol} - Price: ${opt.price}, IV: {opt.implied_volatility}")
        print(f"   Status: Data received without errors")

    except ProviderError as e:
        # Expected for Level 1 without subscription
        print(f"❌ PROVIDER ERROR (Expected for Level 1)")
        print(f"   Error: {e}")
        print(f"   Status: Correctly raised exception for missing subscription")

    except Exception as e:
        # Unexpected error
        print(f"⚠️  UNEXPECTED ERROR")
        print(f"   Error: {type(e).__name__}: {e}")

    finally:
        # Cleanup
        if provider.ib.isConnected():
            provider.ib.disconnect()
            print(f"   Disconnected from gateway")

async def main():
    """Run all tests."""
    print("=" * 60)
    print("🔬 Market Data Type Test Suite")
    print("=" * 60)
    print(f"Gateway: ib-gateway.framas.cloud:4002")
    print(f"Client ID: 10001")
    print(f"Symbol: IWM")
    print(f"Expiry: 2026-01-13")
    print(f"Strike Range: 227.0 - 230.0")

    # Test Level 3 (Delayed) - Should always work
    await test_level(3)
    await asyncio.sleep(2)

    # Test Level 2 (Frozen) - Should work with OPRA subscription
    await test_level(2)
    await asyncio.sleep(2)

    # Test Level 1 (Live) - Should fail with Error 10091 and raise exception
    await test_level(1)

    print("\n" + "=" * 60)
    print("📊 Summary:")
    print("=" * 60)
    print("✅ Level 3 (Delayed): Should succeed with no errors")
    print("✅ Level 2 (Frozen):  Should succeed with OPRA subscription")
    print("❌ Level 1 (Live):    Should fail with ProviderError (missing Level 2 subscription)")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
