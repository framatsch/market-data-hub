import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.admin_auth import AdminPrincipal, admin_auth
from app.admin.provider_config_repository import KNOWN_PROVIDERS, ProviderRuntimeConfig
from app.admin.runtime import get_key_repository, get_provider_config_repository, get_settings_repository
from app.config import settings
from app.providers.base import BaseCompanyProvider, BaseNewsProvider, BaseOptionsProvider, BasePriceProvider
from app.providers.registry import registry
from app.utils.secrets import unwrap_secret
from app.utils.webhooks import validate_webhook_url

try:
    from schwab.auth import client_from_received_url
except ImportError:  # pragma: no cover
    client_from_received_url = None


router = APIRouter(prefix="/api/admin", tags=["Admin"])

_SCHWAB_TOKEN_LIFETIME_DAYS = 7


class TokenExchangeRequest(BaseModel):
    code: str
    code_verifier: str
    redirect_uri: str | None = None


PrincipalDep = Annotated[AdminPrincipal, Depends(admin_auth)]

CREDENTIAL_ALLOWLIST: dict[str, set[str]] = {
    "schwab": {"api_key", "app_secret", "token_json", "alert_webhook_url"},
    "finnhub": {"api_key"},
    "polygon": {"api_key"},
    "lseg": {"app_key", "username", "password"},
}


class KeySaveRequest(BaseModel):
    provider_name: str
    credential_name: str
    value: str


class ProviderConfigUpdate(BaseModel):
    enabled: bool | None = None
    timeout_seconds: float | None = None
    retry_count: int | None = None
    retry_backoff_seconds: float | None = None
    rate_limit_per_sec: float | None = None
    circuit_breaker_enabled: bool | None = None
    circuit_breaker_failure_threshold: int | None = None
    circuit_breaker_reset_seconds: float | None = None
    connection_config: dict[str, Any] | None = None


class SystemDefaultsUpdate(BaseModel):
    default_price_provider: str | None = None
    default_company_provider: str | None = None
    default_options_provider: str | None = None
    default_news_provider: str | None = None


class IbkrGatewayUpdate(BaseModel):
    host: str
    port: int


class SchwabCallbackRequest(BaseModel):
    received_url: str


class AlertWebhookUpdate(BaseModel):
    webhook_url: str
    format: str = "slack"


def _require_oidc_config() -> str:
    if not settings.ADMIN_OIDC_ISSUER or not settings.ADMIN_OIDC_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Admin OIDC is not configured")
    return settings.ADMIN_OIDC_ISSUER.rstrip("/")


def _validate_webhook_url(webhook_url: str) -> None:
    try:
        validate_webhook_url(webhook_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/auth/url")
async def get_admin_auth_url(code_challenge: Annotated[str, Query(min_length=43, max_length=128)]) -> dict[str, str]:
    issuer = _require_oidc_config()
    params = {
        "client_id": settings.ADMIN_OIDC_CLIENT_ID,
        "response_type": "code",
        "scope": "openid profile email",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if settings.ADMIN_OIDC_REDIRECT_URI:
        params["redirect_uri"] = settings.ADMIN_OIDC_REDIRECT_URI
    return {"auth_url": f"{issuer}/authorize?{urlencode(params)}"}


@router.post("/auth/token")
async def exchange_admin_auth_token(payload: TokenExchangeRequest) -> dict[str, Any]:
    issuer = _require_oidc_config()
    data = {
        "grant_type": "authorization_code",
        "client_id": settings.ADMIN_OIDC_CLIENT_ID,
        "code": payload.code,
        "code_verifier": payload.code_verifier,
    }
    redirect_uri = settings.ADMIN_OIDC_REDIRECT_URI or payload.redirect_uri
    if settings.ADMIN_OIDC_REDIRECT_URI and payload.redirect_uri and payload.redirect_uri != settings.ADMIN_OIDC_REDIRECT_URI:
        raise HTTPException(status_code=400, detail="redirect_uri does not match configured admin redirect URI")
    if redirect_uri:
        data["redirect_uri"] = redirect_uri
    client_secret = unwrap_secret(settings.ADMIN_OIDC_CLIENT_SECRET)
    if client_secret:
        data["client_secret"] = client_secret

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(f"{issuer}/token", data=data)
    if response.status_code >= 400:
        raise HTTPException(status_code=401, detail="Token exchange failed")
    return response.json()


@router.get("/auth/me")
async def get_admin_auth_me(principal: PrincipalDep) -> dict[str, Any]:
    return {"user": principal.user, "auth_enabled": principal.auth_enabled}


def _validate_credential(provider_name: str, credential_name: str) -> None:
    credentials = CREDENTIAL_ALLOWLIST.get(provider_name)
    if credentials is None:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider_name}")
    if credential_name not in credentials:
        raise HTTPException(status_code=400, detail=f"Unknown credential: {credential_name} for provider {provider_name}")


@router.get("/keys")
async def list_admin_keys(_principal: PrincipalDep) -> list[dict[str, Any]]:
    metadata = await get_key_repository().list_credentials()
    return [item.__dict__ for item in metadata]


@router.post("/keys")
async def save_admin_key(payload: KeySaveRequest, _principal: PrincipalDep) -> dict[str, Any]:
    _validate_credential(payload.provider_name, payload.credential_name)
    metadata = await get_key_repository().save(payload.provider_name, payload.credential_name, payload.value)
    return metadata.__dict__


@router.get("/credentials")
async def list_admin_credentials(_principal: PrincipalDep) -> list[dict[str, Any]]:
    configured = {
        (item.provider_name, item.credential_name): item
        for item in await get_key_repository().list_credentials()
    }
    response: list[dict[str, Any]] = []
    for provider_name, credentials in CREDENTIAL_ALLOWLIST.items():
        for credential_name in sorted(credentials):
            metadata = configured.get((provider_name, credential_name))
            response.append(
                {
                    "provider": provider_name,
                    "credential_name": credential_name,
                    "set": metadata is not None,
                    "masked_value": "configured" if metadata is not None else None,
                    "updated_at": metadata.updated_at if metadata is not None else None,
                }
            )
    return response


@router.put("/credentials/{provider_name}")
async def update_admin_credentials(
    provider_name: str,
    credentials: dict[str, str],
    _principal: PrincipalDep,
) -> dict[str, Any]:
    if provider_name not in CREDENTIAL_ALLOWLIST:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider_name}")
    updated: list[str] = []
    for credential_name, value in credentials.items():
        _validate_credential(provider_name, credential_name)
        await get_key_repository().save(provider_name, credential_name, value)
        updated.append(credential_name)
    return {"updated": updated, "errors": []}


def _provider_status(name: str, config: ProviderRuntimeConfig) -> dict[str, Any]:
    provider = registry.get_provider_instance(name)
    if not config.enabled:
        return {"name": name, "enabled": False, "status": "disabled", "error": None}
    if registry.is_provider_paused(name):
        return {
            "name": name,
            "enabled": True,
            "status": "paused",
            "error": "Token expired - re-authorization required",
        }
    if provider is None:
        return {"name": name, "enabled": True, "status": "unavailable", "error": "Provider not loaded"}
    return {"name": name, "enabled": True, "status": "healthy", "error": None}


def _system_defaults() -> dict[str, str]:
    return {
        "default_price_provider": registry.default_price_provider,
        "default_company_provider": registry.default_company_provider,
        "default_options_provider": registry.default_options_provider,
        "default_news_provider": registry.default_news_provider,
    }


@router.get("/settings/defaults")
async def get_admin_settings_defaults(_principal: PrincipalDep) -> dict[str, str]:
    return _system_defaults()


@router.put("/settings/defaults")
async def update_admin_settings_defaults(payload: SystemDefaultsUpdate, _principal: PrincipalDep) -> dict[str, str]:
    values = payload.model_dump(exclude_unset=True)
    settings_repo = get_settings_repository()
    for key, value in values.items():
        if value is not None:
            await settings_repo.set(key, value.lower())
    await registry.reload_from_config(get_provider_config_repository(), settings_repo)
    return _system_defaults()


@router.get("/settings/capabilities")
async def get_admin_settings_capabilities(_principal: PrincipalDep) -> dict[str, list[str]]:
    capabilities = {
        "prices": [],
        "options": [],
        "companies": [],
        "news": [],
    }
    for name, provider in sorted(registry.list_provider_instances().items()):
        if isinstance(provider, BasePriceProvider):
            capabilities["prices"].append(name)
        if isinstance(provider, BaseOptionsProvider):
            capabilities["options"].append(name)
        if isinstance(provider, BaseCompanyProvider):
            capabilities["companies"].append(name)
        if isinstance(provider, BaseNewsProvider):
            capabilities["news"].append(name)
    return capabilities


@router.get("/providers")
async def list_admin_providers(_principal: PrincipalDep) -> list[dict[str, Any]]:
    repo = get_provider_config_repository()
    configs = {config.provider_name: config for config in await repo.list_all()}
    return [
        {
            **_provider_status(name, configs[name]),
            "config": configs[name].model_dump(),
        }
        for name in KNOWN_PROVIDERS
    ]


@router.post("/providers/{provider_name}/enable")
async def enable_admin_provider(provider_name: str, _principal: PrincipalDep) -> dict[str, Any]:
    repo = get_provider_config_repository()
    try:
        config = await repo.save(provider_name, {"enabled": True})
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await registry.reload_from_config(repo)
    return _provider_status(provider_name, config)


@router.post("/providers/{provider_name}/disable")
async def disable_admin_provider(provider_name: str, _principal: PrincipalDep) -> dict[str, Any]:
    repo = get_provider_config_repository()
    try:
        config = await repo.save(provider_name, {"enabled": False})
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await registry.reload_from_config(repo)
    return _provider_status(provider_name, config)


@router.get("/providers/{provider_name}/config")
async def get_admin_provider_config(provider_name: str, _principal: PrincipalDep) -> dict[str, Any]:
    try:
        return (await get_provider_config_repository().get(provider_name)).model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/providers/{provider_name}/config")
async def update_admin_provider_config(
    provider_name: str,
    payload: ProviderConfigUpdate,
    _principal: PrincipalDep,
) -> dict[str, Any]:
    values = payload.model_dump(exclude_unset=True)
    try:
        repo = get_provider_config_repository()
        config = await repo.save(provider_name, values)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await registry.reload_from_config(repo)
    return config.model_dump()


@router.put("/providers/ibkr/gateway")
async def update_ibkr_gateway(payload: IbkrGatewayUpdate, _principal: PrincipalDep) -> dict[str, Any]:
    repo = get_provider_config_repository()
    config = await repo.save("ibkr", {"connection_config": {"host": payload.host, "port": payload.port}})
    await registry.reload_from_config(repo)
    return {"name": "ibkr", "connection_config": config.connection_config}


@router.get("/schwab/auth/url")
async def get_schwab_auth_url(_principal: PrincipalDep) -> dict[str, str]:
    key_repo = get_key_repository()
    api_key = await key_repo.get("schwab", "api_key")
    app_secret = await key_repo.get("schwab", "app_secret")
    if not api_key or not app_secret:
        raise HTTPException(status_code=503, detail="Schwab credentials not configured")
    params = {"client_id": api_key, "redirect_uri": settings.SCHWAB_CALLBACK_URL}
    return {"auth_url": f"https://api.schwabapi.com/v1/oauth/authorize?{urlencode(params)}"}


def _extract_token_json(client: Any) -> str:
    token = getattr(getattr(client, "token_metadata", None), "token", None)
    if token is None:
        token = getattr(client, "token", None)
    if token is None:
        token = getattr(getattr(client, "session", None), "token", None)
    if token is None:
        raise ValueError("schwab-py did not return token metadata")
    return token if isinstance(token, str) else json.dumps(token)


@router.post("/schwab/auth/callback")
async def complete_schwab_auth_callback(payload: SchwabCallbackRequest, _principal: PrincipalDep) -> dict[str, Any]:
    if client_from_received_url is None:
        raise HTTPException(status_code=503, detail="schwab-py is not installed")
    key_repo = get_key_repository()
    api_key = await key_repo.get("schwab", "api_key")
    app_secret = await key_repo.get("schwab", "app_secret")
    if not api_key or not app_secret:
        raise HTTPException(status_code=503, detail="Schwab credentials not configured")

    try:
        client = await asyncio.to_thread(
            client_from_received_url,
            api_key=api_key,
            app_secret=app_secret,
            callback_url=settings.SCHWAB_CALLBACK_URL,
            token_path=None,
            received_url=payload.received_url,
        )
        token_json = _extract_token_json(client)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid callback URL: {exc}") from exc

    await key_repo.save("schwab", "token_json", token_json)
    registry.unpause_provider("schwab")
    return {
        "status": "ok",
        "token_expires_at": (datetime.now(timezone.utc) + timedelta(days=_SCHWAB_TOKEN_LIFETIME_DAYS)).isoformat(),
    }


@router.get("/schwab/auth/status")
async def get_schwab_auth_status(_principal: PrincipalDep) -> dict[str, Any]:
    token_json = await get_key_repository().get("schwab", "token_json")
    storage = "sqlite" if token_json else None
    if token_json is None and Path(settings.SCHWAB_TOKEN_PATH).exists():
        storage = "file-fallback"
        token_json = "configured"
    paused = registry.is_provider_paused("schwab")
    if not token_json:
        return {"status": "not_configured", "paused": paused, "token_configured": False}
    if paused:
        return {"status": "expired", "paused": True, "token_configured": True, "storage": storage, "expires_at": None, "days_remaining": 0}
    expires_at = datetime.now(timezone.utc) + timedelta(days=_SCHWAB_TOKEN_LIFETIME_DAYS)
    return {
        "status": "active",
        "paused": False,
        "token_configured": True,
        "storage": storage,
        "expires_at": expires_at.isoformat(),
        "days_remaining": _SCHWAB_TOKEN_LIFETIME_DAYS,
    }


@router.put("/alerts/webhook")
async def update_alert_webhook(payload: AlertWebhookUpdate, _principal: PrincipalDep) -> dict[str, Any]:
    if payload.format not in {"slack", "generic"}:
        raise HTTPException(status_code=422, detail="format must be slack or generic")
    _validate_webhook_url(payload.webhook_url)
    await get_key_repository().save("schwab", "alert_webhook_url", payload.webhook_url)
    repo = get_provider_config_repository()
    config = await repo.get("schwab")
    connection_config = {**config.connection_config, "alert_webhook_format": payload.format}
    await repo.save("schwab", {"connection_config": connection_config})
    return {"status": "configured", "format": payload.format}


@router.post("/alerts/test")
async def test_alert_webhook(_principal: PrincipalDep) -> dict[str, str]:
    webhook_url = await get_key_repository().get("schwab", "alert_webhook_url")
    if not webhook_url:
        raise HTTPException(status_code=503, detail="Alert webhook URL not configured")
    _validate_webhook_url(webhook_url)
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        response = await client.post(webhook_url, json={"text": "Market Data Hub test alert"})
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Webhook returned HTTP {response.status_code}")
    return {"status": "sent"}
