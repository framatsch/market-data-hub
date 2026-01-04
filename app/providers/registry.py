from typing import Dict, Optional, cast
from app.config import settings
from app.providers.base import BasePriceProvider, BaseCompanyProvider, BaseOptionsProvider, BaseNewsProvider
from app.providers.ibkr import IBKRProvider
from app.providers.lseg import LSEGProvider
from app.providers.mock_news import MockNewsProvider
from app.utils.errors import InvalidProviderError

class ProviderRegistry:
    def __init__(self):
        self._providers: Dict[str, object] = {}
        self._initialize_providers()

    def _initialize_providers(self):
        # In a real app, we might lazily load these or load based on config
        self._providers["ibkr"] = IBKRProvider()
        self._providers["lseg"] = LSEGProvider()
        self._providers["mock"] = MockNewsProvider()

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

    def get_news_provider(self, name: Optional[str] = None) -> BaseNewsProvider:
        name = name or "lseg"  # Default to LSEG for news
        provider = self._providers.get(name)
        if not provider or not isinstance(provider, BaseNewsProvider):
            raise InvalidProviderError(name)
        return cast(BaseNewsProvider, provider)

# Global registry instance
registry = ProviderRegistry()

def get_registry() -> ProviderRegistry:
    return registry

def get_provider(provider_type: str, name: Optional[str] = None):
    """
    Get a provider instance by type and name.

    Args:
        provider_type: Type of provider ("price", "company", "options", "news")
        name: Provider name (e.g., "lseg", "ibkr")

    Returns:
        Provider instance

    Raises:
        InvalidProviderError: If provider type or name is invalid
    """
    reg = get_registry()

    if provider_type == "price":
        return reg.get_price_provider(name)
    elif provider_type == "company":
        return reg.get_company_provider(name)
    elif provider_type == "options":
        return reg.get_options_provider(name)
    elif provider_type == "news":
        return reg.get_news_provider(name)
    else:
        raise InvalidProviderError(f"Unknown provider type: {provider_type}")
