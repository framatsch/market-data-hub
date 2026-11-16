import pytest

from app.admin.provider_config_repository import (
    KNOWN_PROVIDERS,
    ProviderConfigRepository,
)


@pytest.fixture
def repository(tmp_path):
    return ProviderConfigRepository(str(tmp_path / "keys.db"))


async def test_provider_config_returns_defaults(repository) -> None:
    config = await repository.get("ibkr")

    assert config.provider_name == "ibkr"
    assert config.enabled is True
    assert config.timeout_seconds > 0
    assert config.connection_config["host"]
    assert config.connection_config["port"]


async def test_provider_config_upserts_runtime_values(repository) -> None:
    saved = await repository.save(
        "finnhub",
        {"timeout_seconds": 12, "retry_count": 4, "rate_limit_per_sec": 2},
    )

    loaded = await repository.get("finnhub")

    assert saved.updated_at
    assert loaded.timeout_seconds == 12
    assert loaded.retry_count == 4
    assert loaded.rate_limit_per_sec == 2


async def test_provider_config_rejects_invalid_values(repository) -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        await repository.save("schwab", {"timeout_seconds": -1})


async def test_provider_config_validates_connection_config_allowlist(repository) -> None:
    await repository.save("ibkr", {"connection_config": {"host": "192.168.1.10", "port": 4001}})

    with pytest.raises(ValueError, match="Unknown connection config"):
        await repository.save("ibkr", {"connection_config": {"unsupported": True}})


async def test_provider_config_rejects_finnhub_api_key_connection_config(repository) -> None:
    with pytest.raises(ValueError, match="Unknown connection config"):
        await repository.save("finnhub", {"connection_config": {"api_key": "secret"}})


async def test_provider_config_drops_legacy_finnhub_api_key_connection_config(repository) -> None:
    with repository._connect() as conn:
        conn.execute(
            """
            INSERT INTO provider_config (
                provider_name, enabled, timeout_seconds, retry_count,
                retry_backoff_seconds, rate_limit_per_sec, circuit_breaker_enabled,
                circuit_breaker_failure_threshold, circuit_breaker_reset_seconds,
                connection_config_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "finnhub",
                1,
                10.0,
                3,
                0.5,
                1.0,
                0,
                5,
                60.0,
                '{"api_key": "secret"}',
                "2026-01-01T00:00:00+00:00",
            ),
        )

    config = await repository.get("finnhub")

    assert config.connection_config == {}


async def test_provider_config_list_all_merges_defaults_and_rows(repository) -> None:
    await repository.save("finnhub", {"enabled": False})

    configs = await repository.list_all()

    assert {config.provider_name for config in configs} == set(KNOWN_PROVIDERS)
    assert next(config for config in configs if config.provider_name == "finnhub").enabled is False


async def test_history_store_intervals_default_update_and_validation(repository) -> None:
    assert (await repository.get("polygon")).history_store_intervals == ["1d"]
    saved = await repository.save("polygon", {"history_store_intervals": ["1w", "1h"]})
    assert saved.history_store_intervals == ["1w", "1h"]
    assert (await repository.get("polygon")).history_store_intervals == ["1h", "1w"]
    assert (await repository.save("polygon", {"history_store_intervals": []})).history_store_intervals == []
    with pytest.raises(ValueError):
        await repository.save("polygon", {"history_store_intervals": ["5m"]})
    assert (await repository.get("polygon")).history_store_intervals == []
    assert (await repository.get("ibkr")).history_store_intervals == ["1d"]


async def test_existing_database_gets_the_new_column(tmp_path) -> None:
    import sqlite3

    from app.admin.provider_config_repository import ProviderConfigRepository

    path = str(tmp_path / "old.db")
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE provider_config (provider_name TEXT PRIMARY KEY, enabled INTEGER NOT NULL,"
            " timeout_seconds REAL NOT NULL, retry_count INTEGER NOT NULL, retry_backoff_seconds REAL NOT NULL,"
            " rate_limit_per_sec REAL NOT NULL, circuit_breaker_enabled INTEGER NOT NULL,"
            " circuit_breaker_failure_threshold INTEGER NOT NULL, circuit_breaker_reset_seconds REAL NOT NULL,"
            " connection_config_json TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO provider_config VALUES ('polygon',1,10,3,0.5,0,0,5,60,'{}','2026-01-01')"
        )
    repo = ProviderConfigRepository(path)
    assert (await repo.get("polygon")).history_store_intervals == ["1d"]
