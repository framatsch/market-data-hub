import logging
import pytest

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
        saved = settings.DEFAULT_PRICE_PROVIDER
        settings.DEFAULT_PRICE_PROVIDER = "ibkr"
        try:
            with caplog.at_level(logging.WARNING):
                reg = ProviderRegistry()

            assert reg.default_price_provider == "lseg"
            assert "DEFAULT_PRICE_PROVIDER" in caplog.text
            assert "ibkr" in caplog.text
            assert "lseg" in caplog.text

            provider = reg.get_price_provider()
            from app.providers.lseg import LSEGProvider
            assert isinstance(provider, LSEGProvider)
        finally:
            settings.DEFAULT_PRICE_PROVIDER = saved

    def test_company_provider_falls_back_when_default_not_enabled(self, caplog):
        """Given ENABLED_PROVIDERS=lseg and DEFAULT_COMPANY_PROVIDER=finnhub,
        the registry should fall back to lseg for company data."""
        settings.ENABLED_PROVIDERS = "lseg"
        saved = settings.DEFAULT_COMPANY_PROVIDER
        settings.DEFAULT_COMPANY_PROVIDER = "finnhub"
        try:
            with caplog.at_level(logging.WARNING):
                reg = ProviderRegistry()

            assert reg.default_company_provider == "lseg"
            assert "DEFAULT_COMPANY_PROVIDER" in caplog.text

            provider = reg.get_company_provider()
            from app.providers.lseg import LSEGProvider
            assert isinstance(provider, LSEGProvider)
        finally:
            settings.DEFAULT_COMPANY_PROVIDER = saved

    def test_options_provider_throws_when_no_alternative(self):
        """Given ENABLED_PROVIDERS=lseg (no options support) and
        DEFAULT_OPTIONS_PROVIDER=ibkr, get_options_provider should raise."""
        settings.ENABLED_PROVIDERS = "lseg"
        saved = settings.DEFAULT_OPTIONS_PROVIDER
        settings.DEFAULT_OPTIONS_PROVIDER = "ibkr"
        try:
            reg = ProviderRegistry()
            from app.utils.errors import InvalidProviderError
            with pytest.raises(InvalidProviderError):
                reg.get_options_provider()
        finally:
            settings.DEFAULT_OPTIONS_PROVIDER = saved

    def test_all_providers_enabled_uses_configured_defaults(self):
        """When all providers are enabled, defaults should stay as configured."""
        settings.ENABLED_PROVIDERS = ""
        # Settings defaults: price=ibkr, company=finnhub, options=ibkr
        # Note: finnhub only implements BaseNewsProvider, not BaseCompanyProvider,
        # so company falls back to 'ibkr' (first loaded provider implementing it)
        reg = ProviderRegistry()

        assert reg.default_price_provider == "ibkr"
        assert reg.default_company_provider == "ibkr"  # finnhub doesn't implement BaseCompanyProvider
        assert reg.default_options_provider == "ibkr"
        assert reg.default_news_provider == "finnhub"

    def test_news_provider_explicit_name_still_works(self):
        """Passing an explicit provider name should bypass the default."""
        settings.ENABLED_PROVIDERS = "lseg,finnhub"
        reg = ProviderRegistry()

        provider = reg.get_news_provider("finnhub")
        from app.providers.finnhub import FinnhubProvider
        assert isinstance(provider, FinnhubProvider)
