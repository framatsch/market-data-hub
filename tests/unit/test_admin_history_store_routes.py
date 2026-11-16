from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin.provider_config_repository import ProviderConfigRepository
from app.admin.runtime import set_admin_runtime
from app.api.routes_admin import router
from app.config import settings
from app.store import engine


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_AUTH_ENABLED", False)
    logger = Mock()
    monkeypatch.setattr("app.api.routes_admin.audit_log", logger)
    set_admin_runtime(provider_config_repository=ProviderConfigRepository(str(tmp_path / "k.db")))
    app = FastAPI()
    app.include_router(router)
    yield TestClient(app), logger
    set_admin_runtime()
    engine.set_session_factory(None)


def test_status_disabled(client):
    http, _ = client
    body = http.get("/api/admin/history-store").json()
    assert body["state"] == "disabled"
    assert body["prices"] is None and body["iv"] is None
    assert body["settings"]["overlap_bars"] == 5


def test_clear_requires_confirm_and_connected_store(client):
    http, logger = client
    assert http.post("/api/admin/history-store/clear", json={"dataset": "all"}).status_code == 422
    assert http.post(
        "/api/admin/history-store/clear", json={"dataset": "all", "confirm": True}
    ).status_code == 503
    assert http.post(
        "/api/admin/history-store/clear", json={"dataset": "x", "confirm": True}
    ).status_code == 422
    logger.info.assert_not_called()


def test_status_never_shows_credentials(client, monkeypatch):
    http, _ = client
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://user:secret@db:5432/mdh")
    body = http.get("/api/admin/history-store").text
    assert "secret" not in body and "user" not in body


def test_provider_config_validates_intervals(client):
    http, _ = client
    ok = http.put("/api/admin/providers/polygon/config", json={"history_store_intervals": ["1d", "1w"]})
    assert ok.status_code == 200 and ok.json()["history_store_intervals"] == ["1d", "1w"]
    bad = http.put("/api/admin/providers/polygon/config", json={"history_store_intervals": ["5m"]})
    assert bad.status_code == 422
    assert http.get("/api/admin/providers/polygon/config").json()["history_store_intervals"] == ["1d", "1w"]


def test_redacted_url():
    assert engine.redacted_database_url("postgresql://u:p@host:5432/db?sslmode=x") == "postgresql://host:5432/db"
    assert engine.redacted_database_url("") == ""
    assert engine.async_database_url("postgres://u:p@h/db").startswith("postgresql+asyncpg://")
