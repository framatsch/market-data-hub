from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_admin_assets_path_traversal_is_rejected() -> None:
    client = TestClient(app)

    response = client.get("/admin/assets/%2e%2e/%2e%2e/%2e%2e/.env")

    assert response.status_code == 404


def test_admin_spa_path_traversal_is_rejected_without_index(monkeypatch) -> None:
    client = TestClient(app)

    def fake_static_dir() -> Path:
        return Path("/tmp/non-existent-admin-dir")

    monkeypatch.setattr("app.main._resolve_admin_static_dir", fake_static_dir)

    response = client.get("/admin/%2e%2e/%2e%2e/%2e%2e/.env")

    assert response.status_code == 404


def test_admin_assets_path_traversal_is_rejected_in_controlled_static_dir(
    monkeypatch, tmp_path: Path
) -> None:
    static_root = tmp_path / "static" / "admin"
    assets_dir = static_root / "assets"
    assets_dir.mkdir(parents=True)
    (assets_dir / "app.js").write_text("console.log('ok')", encoding="utf-8")
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("top-secret", encoding="utf-8")

    monkeypatch.setattr("app.main._resolve_admin_static_dir", lambda: static_root)
    client = TestClient(app)

    ok = client.get("/admin/assets/app.js")
    blocked = client.get("/admin/assets/%2e%2e/%2e%2e/%2e%2e/secret.txt")

    assert ok.status_code == 200
    assert blocked.status_code == 404


def test_admin_spa_path_traversal_is_rejected_in_controlled_static_dir(
    monkeypatch, tmp_path: Path
) -> None:
    static_root = tmp_path / "static" / "admin"
    static_root.mkdir(parents=True)
    (static_root / "index.html").write_text("<html>index</html>", encoding="utf-8")
    (static_root / "inside.txt").write_text("inside", encoding="utf-8")
    secret_file = tmp_path / "outside.txt"
    secret_file.write_text("outside", encoding="utf-8")

    monkeypatch.setattr("app.main._resolve_admin_static_dir", lambda: static_root)
    client = TestClient(app)

    ok = client.get("/admin/inside.txt")
    blocked = client.get("/admin/%2e%2e/%2e%2e/outside.txt")

    assert ok.status_code == 200
    assert blocked.status_code == 404


def test_admin_static_path_with_null_byte_returns_404() -> None:
    client = TestClient(app)

    response = client.get("/admin/assets/%00")

    assert response.status_code == 404
