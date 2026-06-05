from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.admin_auth import AdminAuth, AdminPrincipal, admin_auth
from app.api.routes_admin import router
from app.config import settings


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_AUTH_ENABLED", False)
    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_auth_disabled_allows_me_without_token(client) -> None:
    response = client.get("/api/admin/auth/me")

    assert response.status_code == 200
    assert response.json() == {"user": "local", "auth_enabled": False}


def test_auth_enabled_missing_token_rejected(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ADMIN_AUTH_ENABLED", True)
    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).get("/api/admin/auth/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


def test_auth_enabled_invalid_token_rejected(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ADMIN_AUTH_ENABLED", True)
    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).get("/api/admin/auth/me", headers={"Authorization": "Bearer invalid"})

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid token"}


def test_auth_me_returns_valid_principal(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ADMIN_AUTH_ENABLED", True)

    async def fake_auth():
        return AdminPrincipal(user="alice", auth_enabled=True, claims={"sub": "alice"})

    app = FastAPI()
    app.dependency_overrides[admin_auth] = fake_auth
    app.include_router(router)

    response = TestClient(app).get("/api/admin/auth/me", headers={"Authorization": "Bearer token"})

    assert response.status_code == 200
    assert response.json() == {"user": "alice", "auth_enabled": True}


def test_auth_url_uses_spa_pkce_challenge(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "ADMIN_OIDC_ISSUER", "https://auth.example/application/o/mdh")
    monkeypatch.setattr(settings, "ADMIN_OIDC_CLIENT_ID", "mdh-admin")
    challenge = "a" * 43

    response = client.get(f"/api/admin/auth/url?code_challenge={challenge}")

    assert response.status_code == 200
    auth_url = response.json()["auth_url"]
    assert "client_id=mdh-admin" in auth_url
    assert f"code_challenge={challenge}" in auth_url
    assert "code_challenge_method=S256" in auth_url


def test_token_exchange_proxies_to_oidc(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "ADMIN_OIDC_ISSUER", "https://auth.example/application/o/mdh")
    monkeypatch.setattr(settings, "ADMIN_OIDC_CLIENT_ID", "mdh-admin")

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, data):
            assert url == "https://auth.example/application/o/mdh/token"
            assert data["code"] == "code"
            assert data["code_verifier"] == "verifier"
            return SimpleNamespace(status_code=200, json=lambda: {"access_token": "token", "expires_in": 3600})

    monkeypatch.setattr("app.api.routes_admin.httpx.AsyncClient", FakeAsyncClient)

    response = client.post("/api/admin/auth/token", json={"code": "code", "code_verifier": "verifier"})

    assert response.status_code == 200
    assert response.json() == {"access_token": "token", "expires_in": 3600}


async def test_admin_auth_refreshes_jwks_on_unknown_kid(monkeypatch) -> None:
    auth = AdminAuth()
    auth._jwks = {"keys": [{"kid": "old"}]}
    auth._jwks_loaded_at = 1
    auth._get_jwks = AsyncMock(return_value={"keys": [{"kid": "new", "alg": "RS256"}]})
    monkeypatch.setattr("app.api.admin_auth.jwt.get_unverified_header", lambda token: {"kid": "new"})
    monkeypatch.setattr("app.api.admin_auth.jwt.decode", lambda *args, **kwargs: {"sub": "alice"})

    principal = await auth.validate_credentials(SimpleNamespace(credentials="token"))

    assert principal.user == "alice"
    auth._get_jwks.assert_awaited_once_with()
