import base64
import os
import sqlite3

import pytest

from app.admin.crypto import CryptoService
from app.admin.key_repository import KeyRepository


@pytest.fixture
def repository(tmp_path):
    key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    return KeyRepository(str(tmp_path / "keys.db"), CryptoService(key))


async def test_key_repository_saves_and_gets_plaintext(repository) -> None:
    await repository.save("finnhub", "api_key", "first-key")

    assert await repository.get("finnhub", "api_key") == "first-key"


async def test_key_repository_updates_existing_credential(repository) -> None:
    await repository.save("schwab", "token_json", "old-token")
    await repository.save("schwab", "token_json", "new-token")

    assert await repository.get("schwab", "token_json") == "new-token"
    with sqlite3.connect(repository.db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM api_credentials").fetchone()[0]
    assert count == 1


async def test_key_repository_unknown_returns_none(repository) -> None:
    assert await repository.get("polygon", "api_key") is None


async def test_key_repository_lists_metadata_without_secret_material(repository) -> None:
    await repository.save("finnhub", "api_key", "plain-secret")


    metadata = await repository.list_credentials()


    assert metadata[0].provider_name == "finnhub"
    assert metadata[0].credential_name == "api_key"
    assert metadata[0].status == "configured"
    assert metadata[0].updated_at
    assert "plain-secret" not in repr(metadata)
