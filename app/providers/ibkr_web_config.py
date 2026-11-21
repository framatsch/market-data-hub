"""Validation shared by the IBKR Web API client and runtime config."""

import ipaddress
import ssl
from collections.abc import Mapping
from typing import Any, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import settings


class IbkrWebConnectionConfig(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    base_url: str
    verify_tls: bool
    ca_bundle: str = ""
    account_id: str = ""
    compete: bool = False
    market_data_type: int = Field(default=3, ge=1, le=4)
    max_streams: int = Field(default=80, ge=1, le=100)
    login_url: str = ""

    @classmethod
    def settings_defaults(cls) -> dict[str, Any]:
        return {
            field: getattr(settings, f"IBKRWEB_{field.upper()}")
            for field in cls.model_fields
        }

    @classmethod
    def from_settings(cls, overrides: Mapping[str, Any] | None = None) -> Self:
        return cls.model_validate({**cls.settings_defaults(), **(overrides or {})})

    @model_validator(mode="after")
    def validate_origin(self) -> Self:
        try:
            url = urlsplit(self.base_url)
            host, port = url.hostname, url.port
        except ValueError as exc:
            raise ValueError("base_url must be an HTTPS origin") from exc
        if (
            url.scheme != "https"
            or not host
            or port == 0
            or url.path not in {"", "/"}
            or any(char in self.base_url for char in "?#\\")
            or "@" in url.netloc
            or any(char.isspace() or ord(char) < 32 for char in self.base_url)
        ):
            raise ValueError(
                "base_url must be an HTTPS origin without credentials, a path, query or fragment"
            )
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == "localhost"
        if not (self.verify_tls or self.ca_bundle or loopback or host == "ibkr-cpgw"):
            raise ValueError(
                "verify_tls must be true or ca_bundle set for a non-local gateway"
            )
        if self.login_url:
            try:
                login = urlsplit(self.login_url)
                valid = (
                    login.scheme == "https"
                    and bool(login.hostname)
                    and "@" not in login.netloc
                )
            except ValueError:
                valid = False
            if not valid or any(
                char.isspace() or ord(char) < 32 for char in self.login_url
            ):
                raise ValueError("login_url must be an HTTPS URL without credentials")
        return self

    def verification(self) -> bool | ssl.SSLContext:
        # A configured bundle takes precedence even when verify_tls is false.
        if self.ca_bundle:
            return ssl.create_default_context(cafile=self.ca_bundle)
        return self.verify_tls

    @property
    def origin(self) -> str:
        return self.base_url.rstrip("/")

    @property
    def browser_login_url(self) -> str:
        """Where a person logs in; differs from base_url when MDH reaches the gateway by a service name."""
        return self.login_url or self.origin
