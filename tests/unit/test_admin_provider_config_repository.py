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


async def test_provider_config_list_all_merges_defaults_and_rows(repository) -> None:
    await repository.save("finnhub", {"enabled": False})

    configs = await repository.list_all()

    assert {config.provider_name for config in configs} == set(KNOWN_PROVIDERS)
    assert next(config for config in configs if config.provider_name == "finnhub").enabled is False
