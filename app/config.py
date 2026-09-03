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

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _get_app_version() -> str:
    try:
        pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
        with open(pyproject_path, "rb") as f:
            return tomllib.load(f)["project"]["version"]
    except Exception:
        return "0.0.0"


APP_VERSION = _get_app_version()


class Settings(BaseSettings):
    # General
    APP_NAME: str = "Market Data Hub"
    APP_ENV: Literal["dev", "test", "prod"] = "dev"
    LOG_LEVEL: str = "INFO"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    # Auto-reload (WatchFiles) is for local development ONLY. Never enable in prod:
    # it rebuilds/re-watches the source tree on every change and is not built for stability.
    # Only takes effect when APP_ENV == "dev" AND RELOAD is true.
    RELOAD: bool = False

    # Enabled Providers (comma-separated list, empty = all)
    ENABLED_PROVIDERS: str = ""

    # Admin runtime storage
    APP_ENCRYPTION_KEY: str = ""
    KEYS_DB_PATH: str = "./keys.db"

    # Provider Defaults are now managed via the database and Admin UI.

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
    # Credentials are loaded from keys.db (provider=lseg).
    LSEG_BASE_URL: str = "https://api.lseg.com/v1"

    # LSEG Performance & Validation
    LSEG_RATE_LIMIT_PER_SEC: int = 10  # Max API requests per second to Refinitiv
    LSEG_CACHE_TTL_SECONDS: int = 5  # Cache quote data for X seconds (0 = disabled)
    LSEG_STRICT_VALIDATION: bool = (
        False  # If True, raise error on missing fields; if False, return None
    )

    # Finnhub Provider
    # Credentials are loaded from keys.db (provider=finnhub).
    FINNHUB_BASE_URL: str = "https://finnhub.io/api/v1"
    FINNHUB_RATE_LIMIT_PER_MIN: int = 60  # Free tier: 60 calls per minute
    FINNHUB_FALLBACK_ON_RATE_LIMIT: bool = (
        True  # Fallback to mock provider if rate limited
    )

    # Schwab Provider
    # Credentials are loaded from keys.db (provider=schwab).
    SCHWAB_CALLBACK_URL: str = "http://localhost:8000/api/admin/schwab/callback"  # OAuth2 redirect URI for backend callback flow
    SCHWAB_TIMEOUT_SECONDS: int = (
        30  # Per-request timeout (applied via asyncio.wait_for)
    )
    SCHWAB_RATE_LIMIT_PER_SEC: int = 5  # Sliding-window limit; Schwab allows ~120/min
    SCHWAB_ASYNCIO: bool = True  # True = async httpx client from schwab-py
    SCHWAB_ALERT_WEBHOOK_FORMAT: Literal["slack", "generic", "discord"] = "slack"

    # Admin Auth
    # Set ADMIN_AUTH_ENABLED=false only for local development.
    ADMIN_AUTH_ENABLED: bool = True
    ADMIN_OIDC_ISSUER: str = ""
    ADMIN_OIDC_CLIENT_ID: str = ""
    ADMIN_OIDC_CLIENT_SECRET: SecretStr = SecretStr("")
    ADMIN_OIDC_REDIRECT_URI: str = ""

    # Polygon.io Provider
    # Credentials are loaded from keys.db (provider=polygon).
    POLYGON_BASE_URL: str = "https://api.polygon.io"

    # Prixe Provider
    # Credentials are loaded from keys.db (provider=prixe).
    PRIXE_BASE_URL: str = "https://api.prixe.io"

    # MCP Integration
    MCP_ENABLED: bool = (
        False  # Set to True to expose MCP endpoints at /mcp/sse and /mcp/messages
    )

    # Timeouts & Retries
    PROVIDER_REQUEST_TIMEOUT: float = 10.0
    PROVIDER_MAX_RETRIES: int = 3

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def _validate_production_admin_auth(self) -> "Settings":
        if self.APP_ENV == "prod" and not self.ADMIN_AUTH_ENABLED:
            raise ValueError(
                "ADMIN_AUTH_ENABLED=false is only allowed outside production"
            )
        if self.APP_ENV == "prod" and self.ADMIN_AUTH_ENABLED:
            if not self.ADMIN_OIDC_ISSUER or not self.ADMIN_OIDC_CLIENT_ID:
                raise ValueError(
                    "ADMIN_OIDC_ISSUER and ADMIN_OIDC_CLIENT_ID are required when admin auth is enabled in production"
                )
        return self


settings = Settings()
