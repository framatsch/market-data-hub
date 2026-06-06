import logging
import pytest
from unittest.mock import MagicMock, AsyncMock

from app.config import settings
from app.providers.registry import ProviderRegistry


@pytest.fixture(autouse=True)
def restore_settings_defaults():
    """Restore settings after each test to avoid cross-test pollution."""
    saved = {
        "ENABLED_PROVIDERS": settings.ENABLED_PROVIDERS,
    }
    yield
    settings.ENABLED_PROVIDERS = saved["ENABLED_PROVIDERS"]


class TestProviderFallback:
    def test_price_provider_falls_back_when_default_not_enabled(self, caplog):
        """Given ENABLED_PROVIDERS=lseg and DEFAULT_PRICE_PROVIDER=ibkr,
        the registry should fall back to lseg for price and log a warning."""
        settings.ENABLED_PROVIDERS = "lseg"
        try:
            with caplog.at_level(logging.WARNING):
                reg = ProviderRegistry()

            assert reg.default_price_provider == "lseg"
            assert "default_price_provider" in caplog.text
            assert "ibkr" in caplog.text
            assert "lseg" in caplog.text

            provider = reg.get_price_provider()
            from app.providers.lseg import LSEGProvider
            assert isinstance(provider, LSEGProvider)
        finally:
            pass

    def test_company_provider_falls_back_when_default_not_enabled(self, caplog):
        """Given ENABLED_PROVIDERS=lseg and DEFAULT_COMPANY_PROVIDER=finnhub,
        the registry should fall back to lseg for company data."""
        settings.ENABLED_PROVIDERS = "lseg"
        try:
            with caplog.at_level(logging.WARNING):
                reg = ProviderRegistry()

            assert reg.default_company_provider == "lseg"
            assert "default_company_provider" in caplog.text

            provider = reg.get_company_provider()
            from app.providers.lseg import LSEGProvider
            assert isinstance(provider, LSEGProvider)
        finally:
            pass

    def test_options_provider_throws_when_no_alternative(self):
        """Given ENABLED_PROVIDERS=lseg (no options support) and
        DEFAULT_OPTIONS_PROVIDER=ibkr, get_options_provider should raise."""
        settings.ENABLED_PROVIDERS = "lseg"
        try:
            reg = ProviderRegistry()
            from app.utils.errors import InvalidProviderError
            with pytest.raises(InvalidProviderError):
                reg.get_options_provider()
        finally:
            pass
    def test_all_providers_enabled_uses_configured_defaults(self):
        """When all providers are enabled, defaults should stay as configured."""
        settings.ENABLED_PROVIDERS = ""
        # Settings defaults: price=ibkr, company=ibkr, options=ibkr, news=finnhub
        reg = ProviderRegistry()

        assert reg.default_price_provider == "ibkr"
        assert reg.default_company_provider == "ibkr"
        assert reg.default_options_provider == "ibkr"
        assert reg.default_news_provider == "finnhub"

    def test_news_provider_explicit_name_still_works(self):
        """Passing an explicit provider name should bypass the default."""
        settings.ENABLED_PROVIDERS = "lseg,finnhub"
        reg = ProviderRegistry()

        provider = reg.get_news_provider("finnhub")
        from app.providers.finnhub import FinnhubProvider
        assert isinstance(provider, FinnhubProvider)

    def test_get_provider_invalid_type(self):
        from app.utils.errors import InvalidProviderError
        from app.dependencies import get_provider
        with pytest.raises(InvalidProviderError):
            get_provider("invalid_type", "ibkr")

    def test_get_price_provider_invalid_explicit(self):
        from app.utils.errors import InvalidProviderError
        reg = ProviderRegistry()
        with pytest.raises(InvalidProviderError):
            reg.get_price_provider("non_existent")

    def test_get_company_provider_invalid_explicit(self):
        from app.utils.errors import InvalidProviderError
        reg = ProviderRegistry()
        with pytest.raises(InvalidProviderError):
            reg.get_company_provider("non_existent")

    def test_get_options_provider_invalid_explicit(self):
        from app.utils.errors import InvalidProviderError
        reg = ProviderRegistry()
        with pytest.raises(InvalidProviderError):
            reg.get_options_provider("non_existent")

    def test_get_news_provider_invalid_explicit(self):
        from app.utils.errors import InvalidProviderError
        reg = ProviderRegistry()
        with pytest.raises(InvalidProviderError):
            reg.get_news_provider("non_existent")

    @pytest.mark.asyncio
    async def test_registry_shutdown_error(self):
        reg = ProviderRegistry()
        mock_provider = MagicMock()
        mock_provider.close = AsyncMock(side_effect=Exception("Shutdown fail"))
        reg._providers["test"] = mock_provider
        
        # Should not raise
        await reg.shutdown()


