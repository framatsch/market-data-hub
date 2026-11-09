import asyncio
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.admin.crypto import CryptoService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CredentialMetadata:
    provider_name: str
    credential_name: str
    status: str
    updated_at: str


class KeyRepository:
    def __init__(self, db_path: str, crypto: CryptoService) -> None:
        self.db_path = db_path
        self._crypto = crypto
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _initialize(self) -> None:
        db_parent = Path(self.db_path).expanduser().resolve().parent
        db_parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS api_credentials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider_name TEXT NOT NULL,
                    credential_name TEXT NOT NULL,
                    ciphertext BLOB NOT NULL,
                    iv BLOB NOT NULL,
                    auth_tag BLOB NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(provider_name, credential_name)
                )
                """
            )

    async def save(
        self, provider_name: str, credential_name: str, plaintext: str
    ) -> CredentialMetadata:
        return await asyncio.to_thread(
            self._save_sync, provider_name, credential_name, plaintext
        )

    def _save_sync(
        self, provider_name: str, credential_name: str, plaintext: str
    ) -> CredentialMetadata:
        blob = self._crypto.encrypt(plaintext)
        updated_at = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO api_credentials (
                    provider_name, credential_name, ciphertext, iv, auth_tag, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider_name, credential_name) DO UPDATE SET
                    ciphertext = excluded.ciphertext,
                    iv = excluded.iv,
                    auth_tag = excluded.auth_tag,
                    updated_at = excluded.updated_at
                """,
                (
                    provider_name,
                    credential_name,
                    blob.ciphertext,
                    blob.iv,
                    blob.auth_tag,
                    updated_at,
                ),
            )
        return CredentialMetadata(
            provider_name, credential_name, "configured", updated_at
        )

    async def get(self, provider_name: str, credential_name: str) -> str | None:
        return await asyncio.to_thread(self._get_sync, provider_name, credential_name)

    def get_sync(self, provider_name: str, credential_name: str) -> str | None:
        return self._get_sync(provider_name, credential_name)

    def _get_sync(self, provider_name: str, credential_name: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT ciphertext, iv, auth_tag
                FROM api_credentials
                WHERE provider_name = ? AND credential_name = ?
                """,
                (provider_name, credential_name),
            ).fetchone()
        if row is None:
            return None
        try:
            return self._crypto.decrypt(row[0], row[1], row[2])
        except ValueError:
            logger.warning(
                "Stored credential %s.%s could not be decrypted with current APP_ENCRYPTION_KEY; treating as unconfigured",
                provider_name,
                credential_name,
            )
            return None

    async def list_credentials(self) -> list[CredentialMetadata]:
        return await asyncio.to_thread(self._list_credentials_sync)

    def _list_credentials_sync(self) -> list[CredentialMetadata]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT provider_name, credential_name, updated_at, ciphertext, iv, auth_tag
                FROM api_credentials
                ORDER BY provider_name, credential_name
                """
            ).fetchall()
        credentials: list[CredentialMetadata] = []
        for provider_name, credential_name, updated_at, ciphertext, iv, auth_tag in rows:
            try:
                self._crypto.decrypt(ciphertext, iv, auth_tag)
            except ValueError:
                logger.warning(
                    "Stored credential %s.%s could not be decrypted with current APP_ENCRYPTION_KEY; excluding from configured credentials",
                    provider_name,
                    credential_name,
                )
                continue
            credentials.append(
                CredentialMetadata(
                    provider_name=provider_name,
                    credential_name=credential_name,
                    status="configured",
                    updated_at=updated_at,
                )
            )
        return credentials
