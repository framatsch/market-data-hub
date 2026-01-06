from datetime import datetime
from typing import List, Optional

from app.models.price import PriceBar, PriceQuote
from app.providers.registry import get_registry

class PriceService:
    def __init__(self, registry=None):
        self.registry = registry or get_registry()

    async def get_latest_price(self, symbol: str, provider_name: Optional[str] = None, market_data_type: Optional[int] = None) -> PriceQuote:
        provider = self.registry.get_price_provider(provider_name)
        return await provider.get_last_price(symbol, market_data_type)

    async def get_historical_prices(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
        provider_name: Optional[str] = None
    ) -> List[PriceBar]:
        provider = self.registry.get_price_provider(provider_name)
        return await provider.get_historical_prices(symbol, interval, start, end)

price_service = PriceService()
