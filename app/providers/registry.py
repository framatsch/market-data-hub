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

import logging
import asyncio
from typing import Dict, Optional, cast

from app.admin.provider_config_repository import ProviderConfigRepository, ProviderRuntimeConfig
from app.admin.settings_repository import SettingsRepository
from app.config import settings
from app.providers.base import BasePriceProvider, BaseCompanyProvider, BaseOptionsProvider, BaseNewsProvider
from app.providers.ibkr import IBKRProvider
from app.providers.lseg import LSEGProvider
from app.providers.schwab import SchwabProvider
from app.providers.mock_news import MockNewsProvider
from app.providers.finnhub import FinnhubProvider
from app.providers.polygon import PolygonProvider
from app.providers.prixe import PrixeProvider
from app.utils.errors import InvalidProviderError

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER_FALLBACKS = {
    "default_price_provider": "ibkr",
    "default_company_provider": "ibkr",
    "default_options_provider": "ibkr",
    "default_news_provider": "finnhub",
}


class ProviderRegistry:
    provider_classes = {
        "ibkr": IBKRProvider,
        "lseg": LSEGProvider,
        "schwab": SchwabProvider,
        "mock": MockNewsProvider,
        "finnhub": FinnhubProvider,
        "polygon": PolygonProvider,
        "prixe": PrixeProvider,
    }

    def __init__(self):
        self._providers: Dict[str, object] = {}
        self._reload_lock = asyncio.Lock()
        self.default_price_provider: str = "ibkr"
        self.default_company_provider: str = "finnhub"
        self.default_options_provider: str = "ibkr"
        self.default_news_provider: str = "finnhub"
        self._initialize_providers()

    def _get_reload_lock(self) -> asyncio.Lock:
        return self._reload_lock

    def _resolve_default(self, configured: str, setting_key: str, base_class: type) -> str:
        """Check if the configured default is loaded and valid; fall back otherwise."""
        if configured in self._providers and isinstance(self._providers[configured], base_class):
            return configured
        for name, provider in self._providers.items():
            if isinstance(provider, base_class):
                logger.warning(
                    "%s '%s' is not enabled or does not implement %s. Falling back to '%s'.",
                    setting_key, configured, base_class.__name__, name,
                )
                return name
        logger.error(
            "%s '%s' is not enabled and no alternative provider implements %s.",
            setting_key, configured, base_class.__name__,
        )
        return configured

    def _apply_default_settings(self, system_settings: dict[str, str] | None = None) -> None:
        values = {**DEFAULT_PROVIDER_FALLBACKS, **(system_settings or {})}
        self.default_price_provider = self._resolve_default(
            values["default_price_provider"], "default_price_provider", BasePriceProvider
        )
        self.default_company_provider = self._resolve_default(
            values["default_company_provider"], "default_company_provider", BaseCompanyProvider
        )
        self.default_options_provider = self._resolve_default(
            values["default_options_provider"], "default_options_provider", BaseOptionsProvider
        )
        self.default_news_provider = self._resolve_default(
            values["default_news_provider"], "default_news_provider", BaseNewsProvider
        )

    def _initialize_providers(self):
        # Parse enabled providers from config
        enabled_str = settings.ENABLED_PROVIDERS.strip()
        if enabled_str:
            enabled_list = [p.strip().lower() for p in enabled_str.split(",")]
            # Filter to only requested and valid names
            to_load = {name: cls for name, cls in self.provider_classes.items() if name in enabled_list}
            logger.info(f"Filtered provider loading: {list(to_load.keys())}")
        else:
            to_load = self.provider_classes

        for name, cls in to_load.items():
            try:
                self._providers[name] = cls()
            except ImportError as e:
                logger.warning(f"Provider '{name}' not available: {e}")
            except Exception as e:
                logger.error(f"Failed to initialize provider '{name}': {e}")

        # Resolve effective defaults against actually loaded providers.
        self._apply_default_settings()

    async def reload_from_config(
        self,
        config_repository: ProviderConfigRepository | None = None,
        settings_repository: SettingsRepository | None = None,
    ) -> None:
        if config_repository is None:
            from app.admin.runtime import get_provider_config_repository

            config_repository = get_provider_config_repository()
        if settings_repository is None:
            try:
                from app.admin.runtime import get_settings_repository

                settings_repository = get_settings_repository()
            except RuntimeError:
                settings_repository = None

        async with self._get_reload_lock():
            configs = {config.provider_name: config for config in await config_repository.list_all()}
            system_settings = await settings_repository.get_all() if settings_repository is not None else {}
            enabled = {name for name, config in configs.items() if config.enabled and name in self.provider_classes}

            for name in list(self._providers):
                if name not in enabled:
                    await self._close_provider(name, self._providers.pop(name))

            for name in enabled:
                config = configs[name]
                if name not in self._providers:
                    try:
                        self._providers[name] = self.provider_classes[name]()
                    except ImportError as exc:
                        logger.warning("Provider '%s' not available: %s", name, exc)
                        continue
                    except Exception as exc:
                        logger.error("Failed to initialize provider '%s': %s", name, exc)
                        continue
                self._apply_runtime_config(self._providers[name], config)

            self._apply_default_settings(system_settings)

    async def _close_provider(self, name: str, provider: object) -> None:
        close = getattr(provider, "close", None)
        if close is None:
            return
        try:
            result = close()
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            logger.warning("Error closing provider %s", name, exc_info=True)

    def _apply_runtime_config(self, provider: object, config: ProviderRuntimeConfig) -> None:
        configure = getattr(provider, "configure", None)
        if callable(configure):
            configure(config)
        else:
            setattr(provider, "_runtime_config", config)

    def is_provider_paused(self, name: str) -> bool:
        return bool(getattr(self._providers.get(name), "is_paused", False))

    def unpause_provider(self, name: str) -> None:
        unpause = getattr(self._providers.get(name), "unpause", None)
        if callable(unpause):
            unpause()

    def get_provider_instance(self, name: str) -> object | None:
        return self._providers.get(name)

    def list_provider_instances(self) -> dict[str, object]:
        return dict(self._providers)

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
        for name, provider in list(self._providers.items()):
            await self._close_provider(name, provider)

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
