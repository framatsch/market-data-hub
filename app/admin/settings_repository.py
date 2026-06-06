import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


SETTINGS_ALLOWLIST = frozenset(
    {
        "default_price_provider",
        "default_company_provider",
        "default_options_provider",
        "default_news_provider",
    }
)


class SettingsRepository:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _initialize(self) -> None:
        db_parent = Path(self.db_path).expanduser().resolve().parent
        db_parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS system_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    async def get(self, key: str) -> str | None:
        return await asyncio.to_thread(self._get_sync, key)

    def _get_sync(self, key: str) -> str | None:
        self._validate_key(key)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT value
                FROM system_settings
                WHERE key = ?
                """,
                (key,),
            ).fetchone()
        return None if row is None else str(row[0])

    async def set(self, key: str, value: str) -> dict[str, str]:
        return await asyncio.to_thread(self._set_sync, key, value)

    def _set_sync(self, key: str, value: str) -> dict[str, str]:
        self._validate_key(key)
        updated_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO system_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, updated_at),
            )
        return {"key": key, "value": value, "updated_at": updated_at}

    async def get_all(self) -> dict[str, str]:
        return await asyncio.to_thread(self._get_all_sync)

    def _get_all_sync(self) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT key, value
                FROM system_settings
                ORDER BY key
                """
            ).fetchall()
        return {str(row[0]): str(row[1]) for row in rows}

    @staticmethod
    def _validate_key(key: str) -> None:
        if key not in SETTINGS_ALLOWLIST:
            raise ValueError(f"Unknown system setting: {key}")
