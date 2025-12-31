from typing import Literal
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
    IBKR_MARKET_DATA_TYPE: int = 2  # 2=Frozen (works with OPRA subscription!), 3=Delayed (free, no subscription required)
    IBKR_CONNECT_ON_REQUEST: bool = False
    # Handle subscription errors gracefully
    IBKR_FALLBACK_ON_SUBSCRIPTION_ERROR: bool = True

    # LSEG Provider
    LSEG_APP_KEY: str = "stub-key"  # Refinitiv App Key
    LSEG_USERNAME: str = ""  # Refinitiv platform username
    LSEG_PASSWORD: str = ""  # Refinitiv platform password
    LSEG_BASE_URL: str = "https://api.lseg.com/v1"

    # LSEG Performance & Validation
    LSEG_RATE_LIMIT_PER_SEC: int = 10  # Max API requests per second to Refinitiv
    LSEG_CACHE_TTL_SECONDS: int = 5  # Cache quote data for X seconds (0 = disabled)
    LSEG_STRICT_VALIDATION: bool = False  # If True, raise error on missing fields; if False, return None

    # Timeouts & Retries
    PROVIDER_REQUEST_TIMEOUT: float = 10.0
    PROVIDER_MAX_RETRIES: int = 3

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
