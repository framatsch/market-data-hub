from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # General
    APP_NAME: str = "Market Data Hub"
    APP_ENV: Literal["dev", "test", "prod"] = "dev"
    LOG_LEVEL: str = "INFO"

    # Provider Defaults
    DEFAULT_PRICE_PROVIDER: str = "ibkr"
    DEFAULT_COMPANY_PROVIDER: str = "finnhub"
    DEFAULT_OPTIONS_PROVIDER: str = "ibkr"  # LSEG does NOT support options (missing trapi.data.pricing.read scope)

    # IBKR Provider
    IBKR_HOST: str = "127.0.0.1"
    IBKR_PORT: int = 4001
    IBKR_CLIENT_ID: int = 815
    IBKR_ACCOUNT_ID: str = "DU123456"
    IBKR_ENV: Literal["live", "paper"] = "paper"
    # 1=Live, 2=Frozen, 3=Delayed, 4=Delayed Frozen
    IBKR_MARKET_DATA_TYPE: int = 3  # 3=Delayed (free, no subscription required), 2=Frozen (OPRA subscription), 1=Live (Level 2 subscription)
    IBKR_CONNECT_ON_REQUEST: bool = False
    # Handle subscription errors gracefully
    IBKR_FALLBACK_ON_SUBSCRIPTION_ERROR: bool = True

    # LSEG Provider
    # ⚠️  LSEG subscription does NOT include 'trapi.data.pricing.read' scope
    # → Cannot provide real-time Greeks for options
    # → Use LSEG only for: Stock prices, Company data, News
    # → Use IBKR for: Options data and Greeks
    LSEG_APP_KEY: str = "stub-key"  # Refinitiv App Key
    LSEG_USERNAME: str = ""  # Refinitiv platform username
    LSEG_PASSWORD: str = ""  # Refinitiv platform password
    LSEG_BASE_URL: str = "https://api.lseg.com/v1"

    # LSEG Performance & Validation
    LSEG_RATE_LIMIT_PER_SEC: int = 10  # Max API requests per second to Refinitiv
    LSEG_CACHE_TTL_SECONDS: int = 5  # Cache quote data for X seconds (0 = disabled)
    LSEG_STRICT_VALIDATION: bool = False  # If True, raise error on missing fields; if False, return None

    # Finnhub Provider
    FINNHUB_API_KEY: str = "stub-key"  # Finnhub API Key
    FINNHUB_BASE_URL: str = "https://finnhub.io/api/v1"
    FINNHUB_RATE_LIMIT_PER_MIN: int = 60  # Free tier: 60 calls per minute
    FINNHUB_FALLBACK_ON_RATE_LIMIT: bool = True  # Fallback to mock provider if rate limited

    # MCP Integration
    MCP_ENABLED: bool = False  # Set to True to expose MCP endpoints at /mcp/sse and /mcp/messages

    # Timeouts & Retries
    PROVIDER_REQUEST_TIMEOUT: float = 10.0
    PROVIDER_MAX_RETRIES: int = 3

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
