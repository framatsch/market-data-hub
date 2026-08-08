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
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Any

from app.admin.provider_config_repository import (
    KNOWN_PROVIDERS,
    ProviderConfigRepository,
    ProviderRuntimeConfig,
)
from app.admin.settings_repository import SettingsRepository
from app.config import settings
from app.providers.base import (
    BaseCompanyProvider,
    BaseNewsProvider,
    BaseOptionsProvider,
    BasePriceProvider,
)
from app.providers.finnhub import FinnhubProvider
from app.providers.ibkr import IBKRProvider
from app.providers.lseg import LSEGProvider
from app.providers.mock_news import MockNewsProvider
from app.providers.polygon import PolygonProvider
from app.providers.prixe import PrixeProvider
from app.providers.schwab import SchwabProvider
from app.utils.errors import AppError, InvalidProviderError

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER_FALLBACKS = {
    "default_price_provider": None,
    "default_company_provider": None,
    "default_options_provider": None,
    "default_news_provider": None,
}


class ProviderRegistry:
    provider_classes: dict[str, type[Any]] = {
        "ibkr": IBKRProvider,
        "lseg": LSEGProvider,
        "schwab": SchwabProvider,
        "mock": MockNewsProvider,
        "finnhub": FinnhubProvider,
        "polygon": PolygonProvider,
        "prixe": PrixeProvider,
    }

    def __init__(self) -> None:
        self._providers: dict[str, Any] = {}
        self._reload_lock = asyncio.Lock()
        self._provider_locks: dict[str, asyncio.Lock] = {}
        self._provider_inflight: dict[int, int] = {}
        self._provider_drained: dict[int, asyncio.Event] = {}
        self.default_price_provider: str | None = None
        self.default_company_provider: str | None = None
        self.default_options_provider: str | None = None
        self.default_news_provider: str | None = None
        self._initialize_providers()

    def _get_reload_lock(self) -> asyncio.Lock:
        return self._reload_lock

    def _resolve_default(
        self, configured: str | None, setting_key: str, base_class: type
    ) -> str | None:
        """Return configured provider name only when loaded and implementing the expected base class."""
        if configured is None:
            return None

        provider = self._providers.get(configured)
        if provider is not None and isinstance(provider, base_class):
            return configured

        logger.warning(
            "%s '%s' is not enabled or does not implement %s.",
            setting_key,
            configured,
            base_class.__name__,
        )
        return None

    def _apply_default_settings(
        self, system_settings: dict[str, str | None] | None = None
    ) -> None:
        values = {**DEFAULT_PROVIDER_FALLBACKS, **(system_settings or {})}
        self.default_price_provider = self._resolve_default(
            values["default_price_provider"],
            "default_price_provider",
            BasePriceProvider,
        )
        self.default_company_provider = self._resolve_default(
            values["default_company_provider"],
            "default_company_provider",
            BaseCompanyProvider,
        )
        self.default_options_provider = self._resolve_default(
            values["default_options_provider"],
            "default_options_provider",
            BaseOptionsProvider,
        )
        self.default_news_provider = self._resolve_default(
            values["default_news_provider"], "default_news_provider", BaseNewsProvider
        )

    def _initialize_providers(self) -> None:
        # Parse enabled providers from config
        enabled_str = settings.ENABLED_PROVIDERS.strip()
        if enabled_str:
            enabled_list = [p.strip().lower() for p in enabled_str.split(",")]
            # Filter to only requested and valid names
            to_load = {
                name: cls
                for name, cls in self.provider_classes.items()
                if name in enabled_list
            }
            logger.info(f"Filtered provider loading: {list(to_load.keys())}")
        else:
            to_load = self.provider_classes

        for name, cls in to_load.items():
            try:
                provider = cls()
                provider.name = name
                self._providers[name] = provider
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

        providers_to_close: list[tuple[str, object]] = []

        async with self._get_reload_lock():
            configs = {
                config.provider_name: config
                for config in await config_repository.list_all()
            }
            system_settings = (
                await settings_repository.get_all()
                if settings_repository is not None
                else {}
            )

            for provider_name in KNOWN_PROVIDERS:
                existing_config = configs.get(provider_name)
                if existing_config is None or existing_config.updated_at is None:
                    configs[provider_name] = await config_repository.save(
                        provider_name, {"enabled": False}
                    )

            if settings_repository is not None:
                default_setting_keys = (
                    "default_price_provider",
                    "default_company_provider",
                    "default_options_provider",
                    "default_news_provider",
                )
                for key in default_setting_keys:
                    if key not in system_settings:
                        await settings_repository.set(key, None)
                        system_settings[key] = None

            enabled = {
                name
                for name, config in configs.items()
                if config.enabled and name in self.provider_classes
            }

            current_providers = dict(self._providers)
            next_providers = dict(self._providers)

            for name in list(next_providers):
                if name not in enabled:
                    provider = next_providers.pop(name)
                    providers_to_close.append((name, provider))

            for name in enabled:
                config = configs[name]
                if name not in next_providers:
                    try:
                        provider = self.provider_classes[name]()
                        provider.name = name
                        next_providers[name] = provider
                    except ImportError as exc:
                        logger.warning("Provider '%s' not available: %s", name, exc)
                        continue
                    except Exception as exc:
                        logger.error(
                            "Failed to initialize provider '%s': %s", name, exc
                        )
                        continue
                self._apply_runtime_config(next_providers[name], config)

            for name, provider in current_providers.items():
                replacement = next_providers.get(name)
                if replacement is not None and replacement is not provider:
                    providers_to_close.append((name, provider))

            self._providers = next_providers

            self._apply_default_settings(system_settings)

        for name, provider in providers_to_close:
            await self._close_provider(name, provider)

    async def _close_provider(self, name: str, provider: object) -> None:
        await self._await_provider_drained(provider)
        close = getattr(provider, "close", None)
        if close is None:
            return
        try:
            result = close()
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            logger.warning("Error closing provider %s", name, exc_info=True)

    def _apply_runtime_config(
        self, provider: Any, config: ProviderRuntimeConfig
    ) -> None:
        configure = getattr(provider, "configure", None)
        if callable(configure):
            configure(config)
        else:
            provider._runtime_config = config

    def is_provider_paused(self, name: str) -> bool:
        return bool(getattr(self._providers.get(name), "is_paused", False))

    def unpause_provider(self, name: str) -> None:
        unpause = getattr(self._providers.get(name), "unpause", None)
        if callable(unpause):
            unpause()

    async def _await_provider_drained(self, provider: object) -> None:
        provider_id = id(provider)
        inflight = self._provider_inflight.get(provider_id, 0)
        if inflight <= 0:
            return

        drained_event = self._provider_drained.get(provider_id)
        if drained_event is None:
            drained_event = asyncio.Event()
            self._provider_drained[provider_id] = drained_event

        try:
            await asyncio.wait_for(drained_event.wait(), timeout=5)
        except TimeoutError:
            logger.warning(
                "Timed out waiting for provider %s to drain %s in-flight operations",
                getattr(provider, "name", provider.__class__.__name__),
                inflight,
            )

    async def _acquire_provider(self, provider_name: str, base_class: type) -> Any:
        provider_lock = self._provider_locks.setdefault(provider_name, asyncio.Lock())
        async with provider_lock:
            provider = self._providers.get(provider_name)
            if not provider or not isinstance(provider, base_class):
                raise InvalidProviderError(provider_name)

            provider_id = id(provider)
            self._provider_inflight[provider_id] = (
                self._provider_inflight.get(provider_id, 0) + 1
            )
            return provider

    def _release_provider(self, provider: object) -> None:
        provider_id = id(provider)
        inflight = self._provider_inflight.get(provider_id)
        if inflight is None:
            return
        if inflight <= 1:
            self._provider_inflight.pop(provider_id, None)
            drained_event = self._provider_drained.pop(provider_id, None)
            if drained_event is not None:
                drained_event.set()
            return
        self._provider_inflight[provider_id] = inflight - 1

    def get_provider_instance(self, name: str) -> Any | None:
        return self._providers.get(name)

    def list_provider_instances(self) -> dict[str, object]:
        return dict(self._providers)

    def get_price_provider(self, name: str | None = None) -> BasePriceProvider:
        if name is None and self.default_price_provider is None:
            raise AppError(
                "No price provider configured — enable a provider in the admin UI",
                "PROVIDER_NOT_AVAILABLE",
            )
        provider_name = name or self.default_price_provider
        if provider_name is None:
            raise AppError(
                "No price provider configured — enable a provider in the admin UI",
                "PROVIDER_NOT_AVAILABLE",
            )
        provider = self._providers.get(provider_name)
        if not provider or not isinstance(provider, BasePriceProvider):
            raise InvalidProviderError(provider_name)
        return provider

    def get_company_provider(self, name: str | None = None) -> BaseCompanyProvider:
        if name is None and self.default_company_provider is None:
            raise AppError(
                "No company data provider configured — enable a provider in the admin UI",
                "PROVIDER_NOT_AVAILABLE",
            )
        provider_name = name or self.default_company_provider
        if provider_name is None:
            raise AppError(
                "No company data provider configured — enable a provider in the admin UI",
                "PROVIDER_NOT_AVAILABLE",
            )
        provider = self._providers.get(provider_name)
        if not provider or not isinstance(provider, BaseCompanyProvider):
            raise InvalidProviderError(provider_name)
        return provider

    def get_options_provider(self, name: str | None = None) -> BaseOptionsProvider:
        if name is None and self.default_options_provider is None:
            raise AppError(
                "No options provider configured — enable a provider in the admin UI",
                "PROVIDER_NOT_AVAILABLE",
            )
        provider_name = name or self.default_options_provider
        if provider_name is None:
            raise AppError(
                "No options provider configured — enable a provider in the admin UI",
                "PROVIDER_NOT_AVAILABLE",
            )
        provider = self._providers.get(provider_name)
        if not provider or not isinstance(provider, BaseOptionsProvider):
            raise InvalidProviderError(provider_name)
        return provider

    def get_news_provider(self, name: str | None = None) -> BaseNewsProvider:
        if name is None and self.default_news_provider is None:
            raise AppError(
                "No news provider configured — enable a provider in the admin UI",
                "PROVIDER_NOT_AVAILABLE",
            )
        provider_name = name or self.default_news_provider
        if provider_name is None:
            raise AppError(
                "No news provider configured — enable a provider in the admin UI",
                "PROVIDER_NOT_AVAILABLE",
            )
        provider = self._providers.get(provider_name)
        if not provider or not isinstance(provider, BaseNewsProvider):
            raise InvalidProviderError(provider_name)
        return provider

    @asynccontextmanager
    async def use_price_provider(
        self, name: str | None = None
    ) -> AsyncIterator[BasePriceProvider]:
        if name is None and self.default_price_provider is None:
            raise AppError(
                "No price provider configured — enable a provider in the admin UI",
                "PROVIDER_NOT_AVAILABLE",
            )
        provider_name = name or self.default_price_provider
        if provider_name is None:
            raise AppError(
                "No price provider configured — enable a provider in the admin UI",
                "PROVIDER_NOT_AVAILABLE",
            )
        provider = await self._acquire_provider(provider_name, BasePriceProvider)
        try:
            yield provider
        finally:
            self._release_provider(provider)

    @asynccontextmanager
    async def use_company_provider(
        self, name: str | None = None
    ) -> AsyncIterator[BaseCompanyProvider]:
        if name is None and self.default_company_provider is None:
            raise AppError(
                "No company data provider configured — enable a provider in the admin UI",
                "PROVIDER_NOT_AVAILABLE",
            )
        provider_name = name or self.default_company_provider
        if provider_name is None:
            raise AppError(
                "No company data provider configured — enable a provider in the admin UI",
                "PROVIDER_NOT_AVAILABLE",
            )
        provider = await self._acquire_provider(provider_name, BaseCompanyProvider)
        try:
            yield provider
        finally:
            self._release_provider(provider)

    @asynccontextmanager
    async def use_options_provider(
        self, name: str | None = None
    ) -> AsyncIterator[BaseOptionsProvider]:
        if name is None and self.default_options_provider is None:
            raise AppError(
                "No options provider configured — enable a provider in the admin UI",
                "PROVIDER_NOT_AVAILABLE",
            )
        provider_name = name or self.default_options_provider
        if provider_name is None:
            raise AppError(
                "No options provider configured — enable a provider in the admin UI",
                "PROVIDER_NOT_AVAILABLE",
            )
        provider = await self._acquire_provider(provider_name, BaseOptionsProvider)
        try:
            yield provider
        finally:
            self._release_provider(provider)

    @asynccontextmanager
    async def use_news_provider(
        self, name: str | None = None
    ) -> AsyncIterator[BaseNewsProvider]:
        if name is None and self.default_news_provider is None:
            raise AppError(
                "No news provider configured — enable a provider in the admin UI",
                "PROVIDER_NOT_AVAILABLE",
            )
        provider_name = name or self.default_news_provider
        if provider_name is None:
            raise AppError(
                "No news provider configured — enable a provider in the admin UI",
                "PROVIDER_NOT_AVAILABLE",
            )
        provider = await self._acquire_provider(provider_name, BaseNewsProvider)
        try:
            yield provider
        finally:
            self._release_provider(provider)

    async def shutdown(self) -> None:
        """Gracefully close all providers that expose a close() coroutine."""
        for name, provider in list(self._providers.items()):
            await self._close_provider(name, provider)


# Global registry instance
registry = ProviderRegistry()


def get_registry() -> ProviderRegistry:
    return registry


def get_provider(provider_type: str, name: str | None = None) -> Any:
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
