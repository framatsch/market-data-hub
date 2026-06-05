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

from typing import Literal
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # General
    APP_NAME: str = "Market Data Hub"
    APP_ENV: Literal["dev", "test", "prod"] = "dev"
    LOG_LEVEL: str = "INFO"
    
    # Enabled Providers (comma-separated list, empty = all)
    ENABLED_PROVIDERS: str = ""

    # Admin runtime storage
    APP_ENCRYPTION_KEY: str = ""
    KEYS_DB_PATH: str = "./keys.db"

    # Provider Defaults
    DEFAULT_PRICE_PROVIDER: str = "ibkr"  # Valid: ibkr, lseg, schwab
    DEFAULT_COMPANY_PROVIDER: str = "finnhub"
    DEFAULT_OPTIONS_PROVIDER: str = "ibkr"  # LSEG does NOT support options (missing trapi.data.pricing.read scope)
    DEFAULT_NEWS_PROVIDER: str = "finnhub"

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
    LSEG_PASSWORD: SecretStr = SecretStr("")  # Refinitiv platform password
    LSEG_BASE_URL: str = "https://api.lseg.com/v1"

    # LSEG Performance & Validation
    LSEG_RATE_LIMIT_PER_SEC: int = 10  # Max API requests per second to Refinitiv
    LSEG_CACHE_TTL_SECONDS: int = 5  # Cache quote data for X seconds (0 = disabled)
    LSEG_STRICT_VALIDATION: bool = False  # If True, raise error on missing fields; if False, return None

    # Finnhub Provider
    FINNHUB_API_KEY: SecretStr = SecretStr("stub-key")  # Finnhub API Key
    FINNHUB_BASE_URL: str = "https://finnhub.io/api/v1"
    FINNHUB_RATE_LIMIT_PER_MIN: int = 60  # Free tier: 60 calls per minute
    FINNHUB_FALLBACK_ON_RATE_LIMIT: bool = True  # Fallback to mock provider if rate limited

    # Schwab Provider
    # Credentials: set via environment variables or .env file.
    # For Kubernetes: mount as envFrom secretRef (see k8s/ or docs/schwab-setup.md).
    SCHWAB_API_KEY: SecretStr = SecretStr("")       # Schwab Individual Trader API key
    SCHWAB_APP_SECRET: SecretStr = SecretStr("")    # Schwab app secret (OAuth2 client secret)
    SCHWAB_CALLBACK_URL: str = "https://127.0.0.1:8182"  # OAuth2 redirect URI (for token generation only)
    SCHWAB_TOKEN_PATH: str = "./schwab_token.json"  # Persistent token file; avoid /tmp in containers
    SCHWAB_TIMEOUT_SECONDS: int = 30               # Per-request timeout (applied via asyncio.wait_for)
    SCHWAB_RATE_LIMIT_PER_SEC: int = 5             # Sliding-window limit; Schwab allows ~120/min
    SCHWAB_ASYNCIO: bool = True                    # True = async httpx client from schwab-py
    SCHWAB_ALERT_WEBHOOK_URL: SecretStr = SecretStr("")
    SCHWAB_ALERT_WEBHOOK_FORMAT: Literal["slack", "generic"] = "slack"

    # Admin Auth
    ADMIN_AUTH_ENABLED: bool = False
    ADMIN_OIDC_ISSUER: str = ""
    ADMIN_OIDC_CLIENT_ID: str = ""
    ADMIN_OIDC_CLIENT_SECRET: SecretStr = SecretStr("")

    # Polygon.io Provider
    POLYGON_API_KEY: SecretStr = SecretStr("stub-key")
    POLYGON_BASE_URL: str = "https://api.polygon.io"

    # Prixe Provider
    PRIXE_API_KEY: SecretStr = SecretStr("")
    PRIXE_BASE_URL: str = "https://api.prixe.io"

    # MCP Integration
    MCP_ENABLED: bool = False  # Set to True to expose MCP endpoints at /mcp/sse and /mcp/messages

    # Timeouts & Retries
    PROVIDER_REQUEST_TIMEOUT: float = 10.0
    PROVIDER_MAX_RETRIES: int = 3

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
