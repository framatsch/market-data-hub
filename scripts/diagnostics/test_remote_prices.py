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
Test script for remote IB Gateway price endpoint behavior (stocks).
Tests against: ib-gateway.framas.cloud:4002, Client ID 10001

Expected behavior:
- Level 3 (Delayed): ✅ Data + No errors in log
- Level 2 (Frozen):  ✅ Data + No errors in log (if OPRA subscription)
- Level 1 (Live):    ❌ ProviderError with code PROVIDER_NOT_AVAILABLE
"""
import asyncio
from app.providers.ibkr import IBKRProvider
from app import config
from app.utils.errors import ProviderError

# Remote config override
config.settings.IBKR_HOST = "ib-gateway.framas.cloud"
config.settings.IBKR_PORT = 4002
config.settings.IBKR_CLIENT_ID = 10001

async def test_level(level: int, symbol: str = "IWM"):
    provider = IBKRProvider()
    print(f"\n=== Test Price: market_data_type={level} ===")
    try:
        quote = await provider.get_last_price(symbol, market_data_type=level)
        print(f"✅ SUCCESS: {symbol} price={quote.price} bid={quote.bid} ask={quote.ask}")
    except ProviderError as e:
        print(f"❌ ProviderError: code={e.code} message={e.message}")
    finally:
        if provider.ib.isConnected():
            provider.ib.disconnect()

async def main():
    await test_level(3)
    await asyncio.sleep(1)
    await test_level(2)
    await asyncio.sleep(1)
    await test_level(1)

if __name__ == "__main__":
    asyncio.run(main())
