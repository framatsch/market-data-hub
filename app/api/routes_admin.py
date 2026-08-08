import asyncio
import html
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, cast
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.admin.provider_config_repository import KNOWN_PROVIDERS, ProviderRuntimeConfig
from app.admin.runtime import (
    get_key_repository,
    get_provider_config_repository,
    get_settings_repository,
)
from app.api.admin_auth import AdminPrincipal, admin_auth
from app.config import settings
from app.models.connection import ConnectionTestResult
from app.providers.base import (
    BaseCompanyProvider,
    BaseNewsProvider,
    BaseOptionsProvider,
    BasePriceProvider,
)
from app.providers.registry import registry
from app.utils.secrets import unwrap_secret
from app.utils.webhooks import validate_webhook_url

try:
    from schwab.auth import AuthContext, client_from_received_url, get_auth_context
except ImportError:  # pragma: no cover
    AuthContext = Any
    client_from_received_url = None
    get_auth_context = None


router = APIRouter(prefix="/api/admin", tags=["Admin"])
logger = logging.getLogger(__name__)
_DEFAULT_CONNECTION_TEST_TIMEOUT_SECONDS = 10.0
_LSEG_CONNECTION_TEST_TIMEOUT_SECONDS = 30.0

_SCHWAB_TOKEN_LIFETIME_DAYS = 7
_SCHWAB_PENDING_STATE_TTL = timedelta(minutes=10)
_SCHWAB_CALLBACK_ERROR_TTL = timedelta(minutes=5)
_SCHWAB_CALLBACK_ERROR_KEY = "schwab_callback_error"

_schwab_pending_states: dict[str, tuple[Any, datetime]] = {}
_schwab_callback_error: dict[str, tuple[str, datetime]] = {}


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
    "prixe": {"api_key"},
}

PROVIDER_CAPABILITIES: dict[str, list[str]] = {
    "ibkr": ["prices", "options", "companies"],
    "lseg": ["prices", "companies"],
    "schwab": ["prices", "options"],
    "finnhub": ["news"],
    "polygon": ["prices", "companies"],
    "mock": ["news"],
    "prixe": ["prices"],
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
    client_id: int | None = None
    account_id: str | None = None
    env: Literal["live", "paper"] | None = None
    market_data_type: int | None = None


class SchwabCallbackRequest(BaseModel):
    received_url: str


class SchwabConfigUpdate(BaseModel):
    callback_url: str | None = None
    manual_token_mode: bool | None = None
    force_refresh_token: bool | None = None


class SchwabManualTokenRequest(BaseModel):
    token_json: str


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


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _evict_expired_schwab_states(now: datetime) -> None:
    expired_states = [
        state
        for state, (_, created_at) in _schwab_pending_states.items()
        if now - created_at > _SCHWAB_PENDING_STATE_TTL
    ]
    for state in expired_states:
        _schwab_pending_states.pop(state, None)


def _set_schwab_callback_error(error_message: str) -> None:
    _schwab_callback_error[_SCHWAB_CALLBACK_ERROR_KEY] = (error_message, _utcnow())


def _get_schwab_callback_error() -> str | None:
    error_entry = _schwab_callback_error.get(_SCHWAB_CALLBACK_ERROR_KEY)
    if error_entry is None:
        return None
    error_message, created_at = error_entry
    if _utcnow() - created_at > _SCHWAB_CALLBACK_ERROR_TTL:
        _schwab_callback_error.pop(_SCHWAB_CALLBACK_ERROR_KEY, None)
        return None
    return error_message


@router.get("/auth/url")
async def get_admin_auth_url(
    code_challenge: Annotated[str, Query(min_length=43, max_length=128)],
) -> dict[str, str]:
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
    if (
        settings.ADMIN_OIDC_REDIRECT_URI
        and payload.redirect_uri
        and payload.redirect_uri != settings.ADMIN_OIDC_REDIRECT_URI
    ):
        raise HTTPException(
            status_code=400,
            detail="redirect_uri does not match configured admin redirect URI",
        )
    if redirect_uri:
        data["redirect_uri"] = redirect_uri
    client_secret = unwrap_secret(settings.ADMIN_OIDC_CLIENT_SECRET)
    if client_secret:
        data["client_secret"] = client_secret

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(f"{issuer}/token", data=data)
    if response.status_code >= 400:
        raise HTTPException(status_code=401, detail="Token exchange failed")
    return cast(dict[str, Any], response.json())


@router.get("/auth/me")
async def get_admin_auth_me(principal: PrincipalDep) -> dict[str, Any]:
    return {"user": principal.user, "auth_enabled": principal.auth_enabled}


def _validate_credential(provider_name: str, credential_name: str) -> None:
    credentials = CREDENTIAL_ALLOWLIST.get(provider_name)
    if credentials is None:
        raise HTTPException(
            status_code=400, detail=f"Unknown provider: {provider_name}"
        )
    if credential_name not in credentials:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown credential: {credential_name} for provider {provider_name}",
        )



@router.get("/keys")
async def list_admin_keys(_principal: PrincipalDep) -> list[dict[str, Any]]:
    metadata = await get_key_repository().list_credentials()
    return [item.__dict__ for item in metadata]


@router.post("/keys")
async def save_admin_key(
    payload: KeySaveRequest, _principal: PrincipalDep
) -> dict[str, Any]:
    _validate_credential(payload.provider_name, payload.credential_name)
    metadata = await get_key_repository().save(
        payload.provider_name, payload.credential_name, payload.value
    )
    return metadata.__dict__


@router.get("/credentials")
async def list_admin_credentials(_principal: PrincipalDep) -> list[dict[str, Any]]:
    key_repository = get_key_repository()
    configured = {
        (item.provider_name, item.credential_name): item
        for item in await key_repository.list_credentials()
    }
    response: list[dict[str, Any]] = []
    for provider_name, credentials in CREDENTIAL_ALLOWLIST.items():
        for credential_name in sorted(credentials):
            metadata = configured.get((provider_name, credential_name))
            value = (
                await key_repository.get(provider_name, credential_name)
                if metadata is not None
                else None
            )
            response.append(
                {
                    "provider": provider_name,
                    "credential_name": credential_name,
                    "set": metadata is not None,
                    "value": value,
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
        raise HTTPException(
            status_code=400, detail=f"Unknown provider: {provider_name}"
        )
    updated: list[str] = []
    for credential_name, value in credentials.items():
        _validate_credential(provider_name, credential_name)
        await get_key_repository().save(provider_name, credential_name, value)
        updated.append(credential_name)
    return {"updated": updated, "errors": []}


def _provider_capabilities(name: str, provider: object | None) -> list[str]:
    if provider is None:
        return PROVIDER_CAPABILITIES.get(name, [])

    capabilities = []
    if isinstance(provider, BasePriceProvider):
        capabilities.append("prices")
    if isinstance(provider, BaseOptionsProvider):
        capabilities.append("options")
    if isinstance(provider, BaseCompanyProvider):
        capabilities.append("companies")
    if isinstance(provider, BaseNewsProvider):
        capabilities.append("news")
    return capabilities


def _provider_status(name: str, config: ProviderRuntimeConfig) -> dict[str, Any]:
    provider = registry.get_provider_instance(name)
    capabilities = _provider_capabilities(name, provider)
    if not config.enabled:
        return {
            "name": name,
            "enabled": False,
            "status": "disabled",
            "error": None,
            "capabilities": capabilities,
        }
    if registry.is_provider_paused(name):
        return {
            "name": name,
            "enabled": True,
            "status": "paused",
            "error": "Token expired - re-authorization required",
            "capabilities": capabilities,
        }
    if provider is None:
        return {
            "name": name,
            "enabled": True,
            "status": "unavailable",
            "error": "Provider not loaded",
            "capabilities": capabilities,
        }
    return {
        "name": name,
        "enabled": True,
        "status": "healthy",
        "error": None,
        "capabilities": capabilities,
    }


def _system_defaults() -> dict[str, str]:
    return {
        "default_price_provider": registry.default_price_provider or "",
        "default_company_provider": registry.default_company_provider or "",
        "default_options_provider": registry.default_options_provider or "",
        "default_news_provider": registry.default_news_provider or "",
    }


@router.get("/settings/defaults")
async def get_admin_settings_defaults(_principal: PrincipalDep) -> dict[str, str]:
    return _system_defaults()


@router.put("/settings/defaults")
async def update_admin_settings_defaults(
    payload: SystemDefaultsUpdate, _principal: PrincipalDep
) -> dict[str, str]:
    values = payload.model_dump(exclude_unset=True)
    settings_repo = get_settings_repository()
    for key, value in values.items():
        if value is not None:
            await settings_repo.set(key, value.lower())
    await registry.reload_from_config(get_provider_config_repository(), settings_repo)

    return _system_defaults()


@router.get("/settings/capabilities")
async def get_admin_settings_capabilities(
    _principal: PrincipalDep,
) -> dict[str, list[str]]:
    capabilities: dict[str, list[str]] = {
        "prices": [],
        "options": [],
        "companies": [],
        "news": [],
    }
    for config in await get_provider_config_repository().list_all():
        if not config.enabled:
            continue
        for capability in PROVIDER_CAPABILITIES.get(config.provider_name, []):
            capabilities[capability].append(config.provider_name)
    return capabilities


@router.get("/providers")
async def list_admin_providers(_principal: PrincipalDep) -> list[dict[str, Any]]:
    repo = get_provider_config_repository()
    configs = {config.provider_name: config for config in await repo.list_all()}
    return [
        {
            **_provider_status(name, configs[name]),
            "config": configs[name].model_dump(),
            "config_summary": {
                "timeout_seconds": configs[name].timeout_seconds,
                "retry_count": configs[name].retry_count,
                "rate_limit_per_sec": configs[name].rate_limit_per_sec,
            },
        }
        for name in KNOWN_PROVIDERS
    ]


@router.post("/providers/{provider_name}/enable")
async def enable_admin_provider(
    provider_name: str, _principal: PrincipalDep
) -> dict[str, Any]:
    repo = get_provider_config_repository()
    try:
        config = await repo.save(provider_name, {"enabled": True})
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await registry.reload_from_config(repo)
    return _provider_status(provider_name, config)


@router.post("/providers/{provider_name}/disable")
async def disable_admin_provider(
    provider_name: str, _principal: PrincipalDep
) -> dict[str, Any]:
    repo = get_provider_config_repository()
    try:
        config = await repo.save(provider_name, {"enabled": False})
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await registry.reload_from_config(repo)
    return _provider_status(provider_name, config)


@router.get("/providers/{provider_name}/config")
async def get_admin_provider_config(
    provider_name: str, _principal: PrincipalDep
) -> dict[str, Any]:
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


@router.post(
    "/test-connection/{provider_name}",
    response_model=ConnectionTestResult,
    responses={
        200: {
            "description": "Connection test executed",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "Provider reachable",
                            "value": {
                                "status_code": 200,
                                "success": True,
                                "message": "Connected to IBKR",
                                "details": {"host": "127.0.0.1", "port": 4001},
                            },
                        },
                        "auth_failed": {
                            "summary": "Authentication failed",
                            "value": {
                                "status_code": 401,
                                "success": False,
                                "message": "Authentication failed",
                                "details": {"error": "Invalid credentials"},
                            },
                        },
                        "service_unavailable": {
                            "summary": "Service unavailable",
                            "value": {
                                "status_code": 503,
                                "success": False,
                                "message": "Connection test timeout",
                                "details": {"timeout_seconds": 10.0},
                            },
                        },
                    }
                }
            },
        },
        401: {"description": "Not authenticated"},
        404: {"description": "Provider not found or not enabled"},
        500: {"description": "Unexpected provider test error"},
    },
)
async def test_admin_provider_connection(
    provider_name: str, _principal: PrincipalDep
) -> ConnectionTestResult:
    provider_key = provider_name.lower()
    try:
        provider_config = await get_provider_config_repository().get(provider_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Provider not found") from exc

    if not provider_config.enabled:
        raise HTTPException(status_code=404, detail="Provider not enabled")

    provider = registry.get_provider_instance(provider_key)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    test_connection = getattr(provider, "test_connection", None)
    if not callable(test_connection):
        raise HTTPException(
            status_code=500, detail="Provider does not support connection testing"
        )
    test_connection_call = cast(Callable[[], Awaitable[Any]], test_connection)

    timeout_seconds = max(
        provider_config.timeout_seconds,
        _LSEG_CONNECTION_TEST_TIMEOUT_SECONDS
        if provider_key == "lseg"
        else _DEFAULT_CONNECTION_TEST_TIMEOUT_SECONDS,
    )

    try:
        result_payload = await asyncio.wait_for(
            test_connection_call(), timeout=timeout_seconds
        )
    except TimeoutError:
        timeout_result = ConnectionTestResult(
            status_code=503,
            success=False,
            message="Connection test timeout",
            details={"provider": provider_key, "timeout_seconds": timeout_seconds},
        )
        logger.warning(
            "Connection test failed for provider=%s status_code=%s message=%s",
            provider_key,
            timeout_result.status_code,
            timeout_result.message,
        )
        return timeout_result
    except Exception as exc:
        logger.warning(
            "Connection test raised exception for provider=%s: %s",
            provider_key,
            exc,
        )
        raise HTTPException(
            status_code=500,
            detail={"provider": provider_key, "error": str(exc)},
        ) from exc

    try:
        result = ConnectionTestResult.model_validate(result_payload)
    except Exception as exc:
        logger.warning(
            "Connection test returned invalid payload for provider=%s: %s",
            provider_key,
            exc,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "provider": provider_key,
                "error": "Invalid test_connection() response format",
            },
        ) from exc

    if not result.success:
        logger.warning(
            "Connection test failed for provider=%s status_code=%s message=%s",
            provider_key,
            result.status_code,
            result.message,
        )

    return result


@router.put("/providers/ibkr/gateway")
async def update_ibkr_gateway(
    payload: IbkrGatewayUpdate, _principal: PrincipalDep
) -> dict[str, Any]:
    repo = get_provider_config_repository()
    existing_config = await repo.get("ibkr")
    connection_config = dict(existing_config.connection_config or {})
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    connection_config.update(updates)

    config = await repo.save("ibkr", {"connection_config": connection_config})
    await registry.reload_from_config(repo)
    return {"name": "ibkr", "connection_config": config.connection_config}


async def _get_schwab_callback_url() -> str:
    """Read callback_url from provider_config DB; fall back to settings.SCHWAB_CALLBACK_URL."""
    try:
        repo = get_provider_config_repository()
        config = await repo.get("schwab")
        url = (config.connection_config or {}).get("callback_url")
        if url and isinstance(url, str) and url.strip():
            return url.strip()
    except Exception:
        pass
    return settings.SCHWAB_CALLBACK_URL


async def _get_schwab_connection_config() -> dict[str, Any]:
    """Return the complete Schwab connection_config with defaults."""
    repo = get_provider_config_repository()
    config = await repo.get("schwab")
    cc = dict(config.connection_config or {})
    cc.setdefault("callback_url", settings.SCHWAB_CALLBACK_URL)
    cc.setdefault("manual_token_mode", False)
    cc.setdefault("force_refresh_token", True)
    return cc


@router.get("/schwab/config")
async def get_schwab_config(_principal: PrincipalDep) -> dict[str, Any]:
    """Return Schwab connection_config (callback_url, manual_token_mode, force_refresh_token)."""
    cc = await _get_schwab_connection_config()
    return {"connection_config": cc}


@router.put("/schwab/config")
async def update_schwab_config(
    payload: SchwabConfigUpdate, _principal: PrincipalDep
) -> dict[str, Any]:
    """Save Schwab connection_config fields (callback_url, manual_token_mode, force_refresh_token)."""
    repo = get_provider_config_repository()
    existing = await repo.get("schwab")
    cc = dict(existing.connection_config or {})
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    cc.update(updates)
    saved = await repo.save("schwab", {"connection_config": cc})
    await registry.reload_from_config(repo)
    return {"connection_config": saved.connection_config}


@router.post("/schwab/auth/token/manual")
async def save_schwab_token_manually(
    payload: SchwabManualTokenRequest, _principal: PrincipalDep
) -> dict[str, Any]:
    """Save a manually pasted Schwab token_json directly in the keys DB.

    Used when manual_token_mode=True, when the OAuth redirect does not work and
    the token is manually extracted from the callback URL after login.
    """
    import json as _json

    try:
        _json.loads(payload.token_json)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"token_json is not valid JSON: {exc}"
        ) from exc

    key_repo = get_key_repository()
    await key_repo.save("schwab", "token_json", payload.token_json)
    registry.unpause_provider("schwab")
    _schwab_callback_error.pop(_SCHWAB_CALLBACK_ERROR_KEY, None)
    expires_at = (_utcnow() + timedelta(days=_SCHWAB_TOKEN_LIFETIME_DAYS)).isoformat()
    return {"status": "ok", "token_expires_at": expires_at}



@router.get("/schwab/auth/url")
async def get_schwab_auth_url(_principal: PrincipalDep) -> dict[str, str]:
    if get_auth_context is None:
        raise HTTPException(status_code=503, detail="schwab-py is not installed")

    key_repo = get_key_repository()
    api_key = await key_repo.get("schwab", "api_key")
    app_secret = await key_repo.get("schwab", "app_secret")
    if not api_key or not app_secret:
        raise HTTPException(status_code=503, detail="Schwab credentials not configured")

    callback_url = await _get_schwab_callback_url()
    now = _utcnow()
    _evict_expired_schwab_states(now)
    auth_context = await asyncio.to_thread(
        get_auth_context,
        api_key,
        callback_url=callback_url,
    )
    _schwab_pending_states[auth_context.state] = (auth_context, now)

    return {"auth_url": auth_context.authorization_url}


def _extract_token_json(client: Any) -> str:
    token = getattr(getattr(client, "token_metadata", None), "token", None)
    if token is None:
        token = getattr(client, "token", None)
    if token is None:
        token = getattr(getattr(client, "session", None), "token", None)
    if token is None:
        raise ValueError("schwab-py did not return token metadata")
    return token if isinstance(token, str) else json.dumps(token)


@router.get("/schwab/callback", response_class=HTMLResponse)
async def complete_schwab_auth_callback_redirect(
    request: Request, code: str, state: str
) -> HTMLResponse:
    _ = code
    if client_from_received_url is None:
        return HTMLResponse(
            status_code=503, content="<h1>schwab-py is not installed.</h1>"
        )

    key_repo = get_key_repository()
    api_key = await key_repo.get("schwab", "api_key")
    app_secret = await key_repo.get("schwab", "app_secret")
    if not api_key or not app_secret:
        _set_schwab_callback_error("Schwab credentials not configured")
        return HTMLResponse(
            status_code=400, content="<h1>Schwab credentials not configured.</h1>"
        )

    # If manual_token_mode is active, this callback should never be called. If it
    # is, return a helpful response instead of continuing the flow.

    now = _utcnow()
    _evict_expired_schwab_states(now)
    pending = _schwab_pending_states.pop(state, None)
    if pending is None:
        _set_schwab_callback_error(
            "Invalid or expired state. Please retry authorization."
        )
        return HTMLResponse(
            status_code=400,
            content="<h1>Invalid or expired state. Please retry authorization.</h1>",
        )

    auth_context, created_at = pending
    if now - created_at > _SCHWAB_PENDING_STATE_TTL:
        _set_schwab_callback_error(
            "Invalid or expired state. Please retry authorization."
        )
        return HTMLResponse(
            status_code=400,
            content="<h1>Invalid or expired state. Please retry authorization.</h1>",
        )

    token_holder: dict[str, str] = {}

    def _token_write_func(token: Any) -> None:
        token_holder["token_json"] = (
            token if isinstance(token, str) else json.dumps(token)
        )

    try:
        client = await asyncio.to_thread(
            client_from_received_url,
            api_key,
            app_secret,
            auth_context=auth_context,
            received_url=str(request.url),
            token_write_func=_token_write_func,
        )
        token_json = token_holder.get("token_json") or _extract_token_json(client)
        await key_repo.save("schwab", "token_json", token_json)
        registry.unpause_provider("schwab")
        _schwab_callback_error.pop(_SCHWAB_CALLBACK_ERROR_KEY, None)
        return HTMLResponse(
            status_code=200,
            content="<h1>Authorization successful. You may close this tab.</h1>",
        )
    except Exception as exc:
        error_message = str(exc)
        _set_schwab_callback_error(error_message)
        return HTMLResponse(
            status_code=400,
            content=f"<h1>Authorization failed: {html.escape(error_message)}</h1>",
        )


@router.post("/schwab/auth/callback", deprecated=True)
async def complete_schwab_auth_callback(
    payload: SchwabCallbackRequest, _principal: PrincipalDep
) -> dict[str, Any]:
    """Fallback manual URL flow"""
    if client_from_received_url is None:
        raise HTTPException(status_code=503, detail="schwab-py is not installed")
    key_repo = get_key_repository()
    api_key = await key_repo.get("schwab", "api_key")
    app_secret = await key_repo.get("schwab", "app_secret")
    if not api_key or not app_secret:
        raise HTTPException(status_code=503, detail="Schwab credentials not configured")

    from urllib.parse import parse_qs, urlparse

    parsed_url = urlparse(payload.received_url)
    qs = parse_qs(parsed_url.query)
    state_list = qs.get("state")
    if not state_list:
        raise HTTPException(status_code=400, detail="Missing state parameter in URL")
    state = state_list[0]

    now = _utcnow()
    _evict_expired_schwab_states(now)
    pending = _schwab_pending_states.pop(state, None)
    if pending is None:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired state. Please click 'Open Auth-Link' again.",
        )
    auth_context, _ = pending

    token_holder: dict[str, str] = {}

    def _token_write_func(token: Any) -> None:
        token_holder["token_json"] = (
            token if isinstance(token, str) else json.dumps(token)
        )

    try:
        client = await asyncio.to_thread(
            client_from_received_url,
            api_key,
            app_secret,
            auth_context=auth_context,
            received_url=payload.received_url,
            token_write_func=_token_write_func,
        )
        token_json = token_holder.get("token_json") or _extract_token_json(client)
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid callback URL: {exc}"
        ) from exc

    await key_repo.save("schwab", "token_json", token_json)
    registry.unpause_provider("schwab")
    return {
        "status": "ok",
        "token_expires_at": (
            datetime.now(UTC) + timedelta(days=_SCHWAB_TOKEN_LIFETIME_DAYS)
        ).isoformat(),
    }


@router.get("/schwab/auth/status")
async def get_schwab_auth_status(_principal: PrincipalDep) -> dict[str, Any]:
    callback_error = _get_schwab_callback_error()
    if callback_error:
        return {"status": "callback_error", "error": callback_error, "paused": True}

    token_json = await get_key_repository().get("schwab", "token_json")
    storage = "sqlite" if token_json else None
    paused = registry.is_provider_paused("schwab")
    if not token_json:
        return {"status": "not_configured", "paused": paused, "token_configured": False}
    if paused:
        return {
            "status": "expired",
            "paused": True,
            "token_configured": True,
            "storage": storage,
            "expires_at": None,
            "days_remaining": 0,
        }
    expires_at = datetime.now(UTC) + timedelta(days=_SCHWAB_TOKEN_LIFETIME_DAYS)
    return {
        "status": "active",
        "paused": False,
        "token_configured": True,
        "storage": storage,
        "expires_at": expires_at.isoformat(),
        "days_remaining": _SCHWAB_TOKEN_LIFETIME_DAYS,
    }


@router.get("/alerts/webhook", deprecated=True)
async def get_alert_webhook(_principal: PrincipalDep) -> dict[str, Any]:
    webhook_url = await get_key_repository().get("schwab", "alert_webhook_url")
    repo = get_provider_config_repository()
    config = await repo.get("schwab")
    webhook_format = (
        config.connection_config.get("alert_webhook_format", "slack")
        if config.connection_config
        else "slack"
    )
    return {"webhook_url": webhook_url or "", "format": webhook_format}


@router.put("/alerts/webhook", deprecated=True)
async def update_alert_webhook(
    payload: AlertWebhookUpdate, _principal: PrincipalDep
) -> dict[str, Any]:
    if payload.format not in {"slack", "generic", "discord"}:
        raise HTTPException(
            status_code=422, detail="format must be slack, generic, or discord"
        )
    _validate_webhook_url(payload.webhook_url)
    await get_key_repository().save("schwab", "alert_webhook_url", payload.webhook_url)
    repo = get_provider_config_repository()
    config = await repo.get("schwab")
    connection_config = {
        **config.connection_config,
        "alert_webhook_format": payload.format,
    }
    await repo.save("schwab", {"connection_config": connection_config})
    return {"status": "configured", "format": payload.format}


@router.post("/alerts/test", deprecated=True)
async def test_alert_webhook(_principal: PrincipalDep) -> dict[str, str]:
    webhook_url = await get_key_repository().get("schwab", "alert_webhook_url")
    if not webhook_url:
        raise HTTPException(status_code=503, detail="Alert webhook URL not configured")
    _validate_webhook_url(webhook_url)

    repo = get_provider_config_repository()
    config = await repo.get("schwab")
    webhook_format = (
        config.connection_config.get("alert_webhook_format", "slack")
        if config.connection_config
        else "slack"
    )

    if webhook_format == "discord":
        payload = {"content": "Market Data Hub test alert"}
    elif webhook_format == "slack":
        payload = {"text": "Market Data Hub test alert"}
    else:
        payload = {"message": "Market Data Hub test alert"}

    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        response = await client.post(webhook_url, json=payload)
    if response.status_code >= 400:
        raise HTTPException(
            status_code=502, detail=f"Webhook returned HTTP {response.status_code}"
        )
    return {"status": "sent"}
