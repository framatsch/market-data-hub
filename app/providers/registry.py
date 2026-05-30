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

import asyncio
import logging
from typing import Dict, Optional, cast

from app.config import settings
from app.providers.base import BasePriceProvider, BaseCompanyProvider, BaseOptionsProvider, BaseNewsProvider
from app.providers.ibkr import IBKRProvider
from app.providers.lseg import LSEGProvider
from app.providers.schwab import SchwabProvider
from app.providers.mock_news import MockNewsProvider
from app.providers.finnhub import FinnhubProvider
from app.utils.errors import InvalidProviderError

logger = logging.getLogger(__name__)


class ProviderRegistry:
    def __init__(self):
        self._providers: Dict[str, object] = {}
        self.default_price_provider: str = "ibkr"
        self.default_company_provider: str = "finnhub"
        self.default_options_provider: str = "ibkr"
        self.default_news_provider: str = "finnhub"
        self._initialize_providers()

    def _resolve_default(self, config_key: str, base_class: type) -> str:
        """Check if the configured default is loaded and valid; fall back otherwise."""
        configured = getattr(settings, config_key)
        if configured in self._providers and isinstance(self._providers[configured], base_class):
            return configured
        for name, provider in self._providers.items():
            if isinstance(provider, base_class):
                logger.warning(
                    "%s '%s' is not enabled or does not implement %s. Falling back to '%s'.",
                    config_key, configured, base_class.__name__, name,
                )
                return name
        logger.error(
            "%s '%s' is not enabled and no alternative provider implements %s.",
            config_key, configured, base_class.__name__,
        )
        return configured

    def _initialize_providers(self):
        # All potential providers
        all_available = {
            "ibkr": IBKRProvider,
            "lseg": LSEGProvider,
            "schwab": SchwabProvider,
            "mock": MockNewsProvider,
            "finnhub": FinnhubProvider,
        }

        # Parse enabled providers from config
        enabled_str = settings.ENABLED_PROVIDERS.strip()
        if enabled_str:
            enabled_list = [p.strip().lower() for p in enabled_str.split(",")]
            # Filter to only requested and valid names
            to_load = {name: cls for name, cls in all_available.items() if name in enabled_list}
            logger.info(f"Filtered provider loading: {list(to_load.keys())}")
        else:
            to_load = all_available

        for name, cls in to_load.items():
            try:
                self._providers[name] = cls()
            except ImportError as e:
                logger.warning(f"Provider '{name}' not available: {e}")
            except Exception as e:
                logger.error(f"Failed to initialize provider '{name}': {e}")

        # Resolve effective defaults against actually loaded providers
        self.default_price_provider = self._resolve_default("DEFAULT_PRICE_PROVIDER", BasePriceProvider)
        self.default_company_provider = self._resolve_default("DEFAULT_COMPANY_PROVIDER", BaseCompanyProvider)
        self.default_options_provider = self._resolve_default("DEFAULT_OPTIONS_PROVIDER", BaseOptionsProvider)
        self.default_news_provider = self._resolve_default("DEFAULT_NEWS_PROVIDER", BaseNewsProvider)

    def get_price_provider(self, name: Optional[str] = None) -> BasePriceProvider:
        name = name or self.default_price_provider
        provider = self._providers.get(name)
        if not provider or not isinstance(provider, BasePriceProvider):
            raise InvalidProviderError(name)
        return cast(BasePriceProvider, provider)

    def get_company_provider(self, name: Optional[str] = None) -> BaseCompanyProvider:
        name = name or self.default_company_provider
        provider = self._providers.get(name)
        if not provider or not isinstance(provider, BaseCompanyProvider):
            raise InvalidProviderError(name)
        return cast(BaseCompanyProvider, provider)

    def get_options_provider(self, name: Optional[str] = None) -> BaseOptionsProvider:
        name = name or self.default_options_provider
        provider = self._providers.get(name)
        if not provider or not isinstance(provider, BaseOptionsProvider):
            raise InvalidProviderError(name)
        return cast(BaseOptionsProvider, provider)

    def get_news_provider(self, name: Optional[str] = None) -> BaseNewsProvider:
        name = name or self.default_news_provider
        provider = self._providers.get(name)
        if not provider or not isinstance(provider, BaseNewsProvider):
            raise InvalidProviderError(name)
        return cast(BaseNewsProvider, provider)

    async def shutdown(self) -> None:
        """Gracefully close all providers that expose a close() coroutine."""
        for provider in self._providers.values():
            close = getattr(provider, "close", None)
            if close is not None and asyncio.iscoroutinefunction(close):
                try:
                    await close()
                except Exception:
                    logger.warning("Error closing provider %s", type(provider).__name__, exc_info=True)

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
