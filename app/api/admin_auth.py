import asyncio
import time
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import settings


_JWKS_CACHE_SECONDS = 3600
_MIN_FORCE_REFRESH_INTERVAL = 60.0


@dataclass(frozen=True)
class AdminPrincipal:
    user: str
    auth_enabled: bool
    claims: dict[str, Any]


class AdminAuth:
    def __init__(self) -> None:
        self._bearer = HTTPBearer(auto_error=False)
        self._jwks: dict[str, Any] | None = None
        self._jwks_loaded_at = 0.0
        self._jwks_force_refreshed_at = 0.0
        self._jwks_lock = asyncio.Lock()

    async def __call__(self, request: Request) -> AdminPrincipal:
        if not settings.ADMIN_AUTH_ENABLED:
            return AdminPrincipal(user="local", auth_enabled=False, claims={})

        credentials = await self._bearer(request)
        if credentials is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return await self.validate_credentials(credentials)

    async def validate_credentials(self, credentials: HTTPAuthorizationCredentials) -> AdminPrincipal:
        token = credentials.credentials
        try:
            claims = await self._decode_token(token, refresh_on_unknown_kid=True)
        except HTTPException:
            raise
        except JWTError as exc:
            raise HTTPException(status_code=401, detail="Invalid token") from exc
        return AdminPrincipal(
            user=str(claims.get("sub") or claims.get("preferred_username") or "unknown"),
            auth_enabled=True,
            claims=claims,
        )

    async def _decode_token(self, token: str, refresh_on_unknown_kid: bool) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(token)
        except JWTError as exc:
            raise HTTPException(status_code=401, detail="Invalid token") from exc

        kid = header.get("kid")
        jwks = await self._get_jwks()
        key = self._find_key(jwks, kid)
        if key is None and refresh_on_unknown_kid:
            now = time.monotonic()
            if now - self._jwks_force_refreshed_at >= _MIN_FORCE_REFRESH_INTERVAL:
                self._jwks_force_refreshed_at = now
                jwks = await self._get_jwks(force_refresh=True)
                key = self._find_key(jwks, kid)
        if key is None:
            raise HTTPException(status_code=401, detail="Invalid token")

        return jwt.decode(
            token,
            key,
            algorithms=[key.get("alg", "RS256")],
            audience=settings.ADMIN_OIDC_CLIENT_ID or None,
            issuer=settings.ADMIN_OIDC_ISSUER or None,
            options={"verify_aud": bool(settings.ADMIN_OIDC_CLIENT_ID)},
        )

    async def _get_jwks(self, force_refresh: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if not force_refresh and self._jwks is not None and now - self._jwks_loaded_at < _JWKS_CACHE_SECONDS:
            return self._jwks
        if not settings.ADMIN_OIDC_ISSUER:
            raise HTTPException(status_code=401, detail="Invalid token")

        async with self._jwks_lock:
            now = time.monotonic()
            if not force_refresh and self._jwks is not None and now - self._jwks_loaded_at < _JWKS_CACHE_SECONDS:
                return self._jwks
            issuer = settings.ADMIN_OIDC_ISSUER.rstrip("/")
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{issuer}/.well-known/jwks.json")
                response.raise_for_status()
                self._jwks = response.json()
                self._jwks_loaded_at = now
                assert self._jwks is not None
                return self._jwks

    @staticmethod
    def _find_key(jwks: dict[str, Any], kid: str | None) -> dict[str, Any] | None:
        if kid is None:
            return None
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return key
        return None


admin_auth = AdminAuth()
