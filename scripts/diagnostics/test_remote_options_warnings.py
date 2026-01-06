#!/usr/bin/env python3
"""
Test option chain with remote IB Gateway to check for warnings and open_interest population.
"""
import asyncio
import sys
import logging
import os
from datetime import date
from pathlib import Path

# Set environment BEFORE importing app modules
os.environ['IBKR_HOST'] = 'ib-gateway.framas.cloud'
os.environ['IBKR_PORT'] = '4002'
os.environ['IBKR_CLIENT_ID'] = '10001'

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.providers.ibkr import IBKRProvider

# Configure logging to see all levels
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_options_with_remote_gateway():
    """Test option chain requests with different market data types."""

    provider = IBKRProvider()

    print(f"\n🔗 Connecting to {provider.host}:{provider.port} (Client ID: {provider.client_id})")

    test_cases = [
        {"type": 3, "name": "Level 3 (Delayed)"},
        {"type": 2, "name": "Level 2 (Frozen)"},
        {"type": 1, "name": "Level 1 (Live)"},
    ]

    for test in test_cases:
        print(f"\n{'='*60}")
        print(f"Testing {test['name']} (market_data_type={test['type']})")
        print(f"{'='*60}")

        try:
            chain = await provider.get_option_chain(
                symbol='IWM',
                expiry=date(2026, 1, 7),
                min_strike=250,
                max_strike=256,
                market_data_type=test['type']
            )

            print(f"\n✅ SUCCESS: Got {len(chain.options)} options")

            if chain.options:
                # Show first option details
                opt = chain.options[0]
                print(f"\nFirst option: {opt.symbol}")
                print(f"  - Price: {opt.price}")
                print(f"  - Bid/Ask: {opt.bid}/{opt.ask}")
                print(f"  - Volume: {opt.volume}")
                print(f"  - Open Interest: {opt.open_interest}")
                print(f"  - IV: {opt.implied_volatility}")

                # Count how many have open_interest
                with_oi = sum(1 for o in chain.options if o.open_interest is not None)
                print(f"\n📊 {with_oi}/{len(chain.options)} options have open_interest")

        except Exception as e:
            print(f"\n❌ ERROR: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_options_with_remote_gateway())
