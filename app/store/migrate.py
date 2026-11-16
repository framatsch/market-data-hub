# market-data-hub - FastAPI data service for market and company data
# Copyright (C) 2026  Market Data Hub Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Schema migrations of the history store, run under a PostgreSQL advisory lock."""

from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

MIGRATION_LOCK_KEY = 7_204_001_133


def _config(connection: Connection) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    cfg.attributes["connection"] = connection
    return cfg


def _head(connection: Connection) -> str | None:
    return ScriptDirectory.from_config(_config(connection)).get_current_head()


def _current(connection: Connection) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


def _upgrade(connection: Connection) -> None:
    command.upgrade(_config(connection), "head")


async def ensure_schema(engine: AsyncEngine, migrate: bool = True) -> None:
    """Migrate to head (under an advisory lock) or verify the schema is current."""
    async with engine.connect() as conn:
        if not migrate:
            current = await conn.run_sync(_current)
            head = await conn.run_sync(_head)
            if current != head:
                raise RuntimeError(
                    "History store schema is missing or outdated and "
                    "HISTORY_STORE_MIGRATE_ON_STARTUP is false"
                )
            return
        await conn.execute(
            text("SELECT pg_advisory_lock(:key)"), {"key": MIGRATION_LOCK_KEY}
        )
        try:
            await conn.run_sync(_upgrade)
            await conn.commit()
        finally:
            await conn.rollback()
            await conn.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": MIGRATION_LOCK_KEY}
            )
            await conn.commit()


def metadata() -> Any:
    from app.store.models import Base

    return Base.metadata
