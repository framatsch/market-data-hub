#!/usr/bin/env python3
"""Check what data IBKR provides for different market data types."""
import asyncio
from ib_async import IB, Stock
import logging

logging.basicConfig(level=logging.WARNING)

async def test_market_data_type(host, port, client_id, mdt):
    ib = IB()
    await ib.connectAsync(host, port, clientId=client_id)
    ib.reqMarketDataType(mdt)

    contract = Stock('IWM', 'SMART', 'USD')
    await ib.qualifyContractsAsync(contract)

    ticker = ib.reqMktData(contract, '', True, False)  # snapshot
    await asyncio.sleep(5)

    print(f"\n{'='*70}")
    print(f"Market Data Type {mdt} (1=Live, 2=Frozen, 3=Delayed):")
    print(f"{'='*70}")
    print(f"bid            = {ticker.bid}")
    print(f"ask            = {ticker.ask}")
    print(f"last           = {ticker.last}")
    print(f"close          = {ticker.close}")
    print(f"volume         = {ticker.volume}")
    print(f"time           = {ticker.time}")
    print(f"marketDataType = {ticker.marketDataType}")

    ib.disconnect()

async def main():
    host = 'ib-gateway.framas.cloud'
    port = 4002

    # Test each market data type
    for mdt in [2, 3]:  # Skip 1 since it needs subscription
        await test_market_data_type(host, port, 99997 - mdt, mdt)
        await asyncio.sleep(2)

if __name__ == '__main__':
    asyncio.run(main())
