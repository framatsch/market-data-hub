from typing import Dict, Type, Optional, cast
from app.config import settings
from app.providers.base import BasePriceProvider, BaseCompanyProvider, BaseOptionsProvider
from app.providers.ibkr import IBKRProvider
from app.providers.lseg import LSEGProvider
from app.utils.errors import InvalidProviderError

class ProviderRegistry:
    def __init__(self):
        self._providers: Dict[str, object] = {}
        self._initialize_providers()

    def _initialize_providers(self):
        # In a real app, we might lazily load these or load based on config
        self._providers["ibkr"] = IBKRProvider()
        self._providers["lseg"] = LSEGProvider()

    def get_price_provider(self, name: Optional[str] = None) -> BasePriceProvider:
        name = name or settings.DEFAULT_PRICE_PROVIDER
        provider = self._providers.get(name)
        if not provider or not isinstance(provider, BasePriceProvider):
            raise InvalidProviderError(name)
        return cast(BasePriceProvider, provider)

    def get_company_provider(self, name: Optional[str] = None) -> BaseCompanyProvider:
        name = name or settings.DEFAULT_COMPANY_PROVIDER
        provider = self._providers.get(name)
        if not provider or not isinstance(provider, BaseCompanyProvider):
            raise InvalidProviderError(name)
        return cast(BaseCompanyProvider, provider)

    def get_options_provider(self, name: Optional[str] = None) -> BaseOptionsProvider:
        name = name or settings.DEFAULT_OPTIONS_PROVIDER
        provider = self._providers.get(name)
        if not provider or not isinstance(provider, BaseOptionsProvider):
            raise InvalidProviderError(name)
        return cast(BaseOptionsProvider, provider)

# Global registry instance
registry = ProviderRegistry()

def get_registry() -> ProviderRegistry:
    return registry
