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
