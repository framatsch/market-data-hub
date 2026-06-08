import pytest

from app.config import settings
from app.providers.registry import ProviderRegistry
from app.utils.errors import AppError, InvalidProviderError


@pytest.fixture(autouse=True)
def restore_settings_defaults():
    saved = {"ENABLED_PROVIDERS": settings.ENABLED_PROVIDERS}
    yield
    settings.ENABLED_PROVIDERS = saved["ENABLED_PROVIDERS"]


class TestProviderDefaults:
    def test_price_provider_raises_503_when_no_default_configured(self):
        settings.ENABLED_PROVIDERS = ""
        reg = ProviderRegistry()

        with pytest.raises(AppError, match="No price provider configured"):
            reg.get_price_provider()

    def test_options_provider_raises_503_when_no_default_configured(self):
        settings.ENABLED_PROVIDERS = ""
        reg = ProviderRegistry()

        with pytest.raises(AppError, match="No options provider configured"):
            reg.get_options_provider()

    def test_company_provider_raises_503_when_no_default_configured(self):
        settings.ENABLED_PROVIDERS = ""
        reg = ProviderRegistry()

        with pytest.raises(AppError, match="No company data provider configured"):
            reg.get_company_provider()

    def test_news_provider_raises_503_when_no_default_configured(self):
        settings.ENABLED_PROVIDERS = ""
        reg = ProviderRegistry()

        with pytest.raises(AppError, match="No news provider configured"):
            reg.get_news_provider()

    def test_explicit_provider_name_bypasses_default_check(self):
        settings.ENABLED_PROVIDERS = "ibkr,finnhub"
        reg = ProviderRegistry()

        assert reg.get_price_provider("ibkr") is not None
        assert reg.get_news_provider("finnhub") is not None

    def test_explicit_missing_provider_raises_invalid_provider(self):
        settings.ENABLED_PROVIDERS = "ibkr,finnhub"
        reg = ProviderRegistry()

        with pytest.raises(InvalidProviderError):
            reg.get_price_provider("non_existent")

        with pytest.raises(InvalidProviderError):
            reg.get_company_provider("non_existent")

        with pytest.raises(InvalidProviderError):
            reg.get_options_provider("non_existent")

        with pytest.raises(InvalidProviderError):
            reg.get_news_provider("non_existent")
