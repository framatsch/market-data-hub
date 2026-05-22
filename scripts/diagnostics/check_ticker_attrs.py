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
"""Check what attributes the Ticker object has for options."""
import asyncio
from ib_async import IB, Option
import logging

logging.basicConfig(level=logging.INFO)

async def main():
    ib = IB()
    await ib.connectAsync('ib-gateway.framas.cloud', 4002, clientId=99998)

    # Test with an option contract
    contract = Option('IWM', '20260107', 250, 'C', 'SMART')
    await ib.qualifyContractsAsync(contract)

    print(f"Qualified contract: {contract}")

    # Request market data
    ticker = ib.reqMktData(contract, '', True, False)
    await asyncio.sleep(5)

    print(f"\n{'='*60}")
    print("Ticker object attributes:")
    print(f"{'='*60}")

    attrs = [a for a in dir(ticker) if not a.startswith('_')]
    for attr in sorted(attrs):
        try:
            val = getattr(ticker, attr)
            if not callable(val):
                print(f"{attr:30} = {val}")
        except:
            pass

    print(f"\n{'='*60}")
    print("Checking for 'openInterest' variants:")
    print(f"{'='*60}")
    variants = ['openInterest', 'open_interest', 'openInt', 'volume']
    for v in variants:
        has_it = hasattr(ticker, v)
        val = getattr(ticker, v, None) if has_it else None
        print(f"{v:30} exists={has_it:5} value={val}")

    ib.disconnect()

if __name__ == '__main__':
    asyncio.run(main())
