import sqlite3

import pytest

from app.admin.settings_repository import SettingsRepository


async def test_settings_repository_initializes_system_settings_table(tmp_path) -> None:
    db_path = tmp_path / "keys.db"

    SettingsRepository(str(db_path))

    with sqlite3.connect(db_path) as conn:
        columns = conn.execute("PRAGMA table_info(system_settings)").fetchall()

    assert [column[1] for column in columns] == ["key", "value", "updated_at"]


async def test_settings_repository_get_set_and_get_all(tmp_path) -> None:
    repository = SettingsRepository(str(tmp_path / "keys.db"))

    assert await repository.get("default_price_provider") is None

    saved = await repository.set("default_price_provider", "lseg")
    await repository.set("default_news_provider", "finnhub")

    assert saved["key"] == "default_price_provider"
    assert saved["value"] == "lseg"
    assert saved["updated_at"]
    assert await repository.get("default_price_provider") == "lseg"
    assert await repository.get_all() == {
        "default_news_provider": "finnhub",
        "default_price_provider": "lseg",
    }


async def test_settings_repository_set_updates_existing_value(tmp_path) -> None:
    repository = SettingsRepository(str(tmp_path / "keys.db"))

    await repository.set("default_options_provider", "ibkr")
    await repository.set("default_options_provider", "schwab")

    assert await repository.get("default_options_provider") == "schwab"


async def test_settings_repository_rejects_unknown_key(tmp_path) -> None:
    repository = SettingsRepository(str(tmp_path / "keys.db"))

    with pytest.raises(ValueError, match="Unknown system setting"):
        await repository.set("unexpected", "value")


async def test_settings_repository_rejects_removed_logo_url_key(tmp_path) -> None:
    repository = SettingsRepository(str(tmp_path / "keys.db"))

    with pytest.raises(ValueError, match="Unknown system setting"):
        await repository.set("logo_url", "/admin/logo.svg")
