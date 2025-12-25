from typing import Literal, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # General
    APP_NAME: str = "Market Data Hub"
    APP_ENV: Literal["dev", "test", "prod"] = "dev"
    LOG_LEVEL: str = "INFO"

    # Provider Defaults
    DEFAULT_PRICE_PROVIDER: str = "ibkr"
    DEFAULT_COMPANY_PROVIDER: str = "lseg"
    DEFAULT_OPTIONS_PROVIDER: str = "ibkr"

    # IBKR Provider
    IBKR_HOST: str = "127.0.0.1"
    IBKR_PORT: int = 4001
    IBKR_CLIENT_ID: int = 815
    IBKR_ACCOUNT_ID: str = "DU123456"
    IBKR_ENV: Literal["live", "paper"] = "paper"
    # 1=Live, 2=Frozen, 3=Delayed, 4=Delayed Frozen
    IBKR_MARKET_DATA_TYPE: int = 3  # 3=Delayed (free, no subscription required), 1=Live (requires subscription)
    IBKR_CONNECT_ON_REQUEST: bool = False
    # Handle subscription errors gracefully
    IBKR_FALLBACK_ON_SUBSCRIPTION_ERROR: bool = True

    # LSEG Provider
    LSEG_BASE_URL: str = "https://api.lseg.com/v1"
    LSEG_API_KEY: str = "stub-key"

    # Timeouts & Retries
    PROVIDER_REQUEST_TIMEOUT: float = 10.0
    PROVIDER_MAX_RETRIES: int = 3

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
