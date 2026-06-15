import asyncio
import json
import sqlite3
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings


KNOWN_PROVIDERS = ("ibkr", "lseg", "schwab", "mock", "finnhub", "polygon", "prixe")

CONNECTION_CONFIG_ALLOWLIST: dict[str, set[str]] = {
    "ibkr": {"host", "port", "client_id", "account_id", "env", "market_data_type"},
    "schwab": {"callback_url", "alert_webhook_format"},
    "lseg": set(),
    "finnhub": set(),
    "polygon": set(),
    "prixe": set(),
    "mock": set(),
}


@dataclass(frozen=True)
class ProviderRuntimeConfig:
    provider_name: str
    enabled: bool
    timeout_seconds: float
    retry_count: int
    retry_backoff_seconds: float
    rate_limit_per_sec: float
    circuit_breaker_enabled: bool
    circuit_breaker_failure_threshold: int
    circuit_breaker_reset_seconds: float
    connection_config: dict[str, Any]
    updated_at: str | None = None

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


class ProviderConfigRepository:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        db_parent = Path(self.db_path).expanduser().resolve().parent
        db_parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_config (
                    provider_name TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL,
                    timeout_seconds REAL NOT NULL,
                    retry_count INTEGER NOT NULL,
                    retry_backoff_seconds REAL NOT NULL,
                    rate_limit_per_sec REAL NOT NULL,
                    circuit_breaker_enabled INTEGER NOT NULL,
                    circuit_breaker_failure_threshold INTEGER NOT NULL,
                    circuit_breaker_reset_seconds REAL NOT NULL,
                    connection_config_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    async def get(self, provider_name: str) -> ProviderRuntimeConfig:
        return await asyncio.to_thread(self._get_sync, provider_name)

    def _get_sync(self, provider_name: str) -> ProviderRuntimeConfig:
        self._validate_provider(provider_name)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT provider_name, enabled, timeout_seconds, retry_count,
                    retry_backoff_seconds, rate_limit_per_sec, circuit_breaker_enabled,
                    circuit_breaker_failure_threshold, circuit_breaker_reset_seconds,
                    connection_config_json, updated_at
                FROM provider_config
                WHERE provider_name = ?
                """,
                (provider_name,),
            ).fetchone()
        if row is None:
            return self._default_config(provider_name)
        return self._row_to_config(row)

    async def save(self, provider_name: str, config: ProviderRuntimeConfig | dict[str, Any]) -> ProviderRuntimeConfig:
        return await asyncio.to_thread(self._save_sync, provider_name, config)

    def _save_sync(self, provider_name: str, config: ProviderRuntimeConfig | dict[str, Any]) -> ProviderRuntimeConfig:
        current = self._get_sync(provider_name)
        if isinstance(config, ProviderRuntimeConfig):
            candidate = replace(config, provider_name=provider_name)
        else:
            allowed = {field.name for field in ProviderRuntimeConfig.__dataclass_fields__.values()}
            values = current.model_dump()
            values.update({key: value for key, value in config.items() if key in allowed})
            values["provider_name"] = provider_name
            candidate = ProviderRuntimeConfig(**values)
        candidate = replace(candidate, updated_at=datetime.now(timezone.utc).isoformat())
        self._validate_config(candidate)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO provider_config (
                    provider_name, enabled, timeout_seconds, retry_count,
                    retry_backoff_seconds, rate_limit_per_sec, circuit_breaker_enabled,
                    circuit_breaker_failure_threshold, circuit_breaker_reset_seconds,
                    connection_config_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider_name) DO UPDATE SET
                    enabled = excluded.enabled,
                    timeout_seconds = excluded.timeout_seconds,
                    retry_count = excluded.retry_count,
                    retry_backoff_seconds = excluded.retry_backoff_seconds,
                    rate_limit_per_sec = excluded.rate_limit_per_sec,
                    circuit_breaker_enabled = excluded.circuit_breaker_enabled,
                    circuit_breaker_failure_threshold = excluded.circuit_breaker_failure_threshold,
                    circuit_breaker_reset_seconds = excluded.circuit_breaker_reset_seconds,
                    connection_config_json = excluded.connection_config_json,
                    updated_at = excluded.updated_at
                """,
                (
                    candidate.provider_name,
                    int(candidate.enabled),
                    candidate.timeout_seconds,
                    candidate.retry_count,
                    candidate.retry_backoff_seconds,
                    candidate.rate_limit_per_sec,
                    int(candidate.circuit_breaker_enabled),
                    candidate.circuit_breaker_failure_threshold,
                    candidate.circuit_breaker_reset_seconds,
                    json.dumps(candidate.connection_config, sort_keys=True),
                    candidate.updated_at,
                ),
            )
        return candidate

    async def list_all(self) -> list[ProviderRuntimeConfig]:
        return await asyncio.to_thread(self._list_all_sync)

    def _list_all_sync(self) -> list[ProviderRuntimeConfig]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT provider_name, enabled, timeout_seconds, retry_count,
                    retry_backoff_seconds, rate_limit_per_sec, circuit_breaker_enabled,
                    circuit_breaker_failure_threshold, circuit_breaker_reset_seconds,
                    connection_config_json, updated_at
                FROM provider_config
                """
            ).fetchall()
        configs = {provider_name: self._default_config(provider_name) for provider_name in KNOWN_PROVIDERS}
        configs.update({row["provider_name"]: self._row_to_config(row) for row in rows})
        return [configs[provider_name] for provider_name in KNOWN_PROVIDERS]

    def _row_to_config(self, row: sqlite3.Row) -> ProviderRuntimeConfig:
        connection_config = json.loads(row["connection_config_json"]) if row["connection_config_json"] else {}
        allowed_connection_keys = CONNECTION_CONFIG_ALLOWLIST[row["provider_name"]]
        connection_config = {
            key: value
            for key, value in connection_config.items()
            if key in allowed_connection_keys
        }
        return ProviderRuntimeConfig(
            provider_name=row["provider_name"],
            enabled=bool(row["enabled"]),
            timeout_seconds=float(row["timeout_seconds"]),
            retry_count=int(row["retry_count"]),
            retry_backoff_seconds=float(row["retry_backoff_seconds"]),
            rate_limit_per_sec=float(row["rate_limit_per_sec"]),
            circuit_breaker_enabled=bool(row["circuit_breaker_enabled"]),
            circuit_breaker_failure_threshold=int(row["circuit_breaker_failure_threshold"]),
            circuit_breaker_reset_seconds=float(row["circuit_breaker_reset_seconds"]),
            connection_config=connection_config,
            updated_at=row["updated_at"],
        )

    def _default_config(self, provider_name: str) -> ProviderRuntimeConfig:
        enabled = self._default_enabled(provider_name)
        connection_config = self._default_connection_config(provider_name)
        return ProviderRuntimeConfig(
            provider_name=provider_name,
            enabled=enabled,
            timeout_seconds=float(settings.PROVIDER_REQUEST_TIMEOUT),
            retry_count=int(settings.PROVIDER_MAX_RETRIES),
            retry_backoff_seconds=0.5,
            rate_limit_per_sec=float(self._default_rate_limit(provider_name)),
            circuit_breaker_enabled=False,
            circuit_breaker_failure_threshold=5,
            circuit_breaker_reset_seconds=60.0,
            connection_config=connection_config,
            updated_at=None,
        )

    def _default_enabled(self, provider_name: str) -> bool:
        enabled_str = settings.ENABLED_PROVIDERS.strip()
        if not enabled_str:
            return True
        enabled = {name.strip().lower() for name in enabled_str.split(",") if name.strip()}
        return provider_name in enabled

    def _default_rate_limit(self, provider_name: str) -> float:
        if provider_name == "schwab":
            return float(settings.SCHWAB_RATE_LIMIT_PER_SEC)
        if provider_name == "lseg":
            return float(settings.LSEG_RATE_LIMIT_PER_SEC)
        if provider_name == "finnhub":
            return float(settings.FINNHUB_RATE_LIMIT_PER_MIN / 60)
        return 0.0

    def _default_connection_config(self, provider_name: str) -> dict[str, Any]:
        if provider_name == "ibkr":
            return {
                "host": settings.IBKR_HOST,
                "port": settings.IBKR_PORT,
                "client_id": settings.IBKR_CLIENT_ID,
                "account_id": settings.IBKR_ACCOUNT_ID,
                "env": settings.IBKR_ENV,
                "market_data_type": settings.IBKR_MARKET_DATA_TYPE,
            }
        if provider_name == "schwab":
            return {
                "callback_url": settings.SCHWAB_CALLBACK_URL,
            }
        return {}

    def _validate_provider(self, provider_name: str) -> None:
        if provider_name not in KNOWN_PROVIDERS:
            raise ValueError(f"Unknown provider: {provider_name}")

    def _validate_config(self, config: ProviderRuntimeConfig) -> None:
        self._validate_provider(config.provider_name)
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than 0")
        if config.retry_count < 0:
            raise ValueError("retry_count must be non-negative")
        if config.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be non-negative")
        if config.rate_limit_per_sec < 0:
            raise ValueError("rate_limit_per_sec must be non-negative")
        if config.circuit_breaker_failure_threshold < 1:
            raise ValueError("circuit_breaker_failure_threshold must be at least 1")
        if config.circuit_breaker_reset_seconds <= 0:
            raise ValueError("circuit_breaker_reset_seconds must be greater than 0")
        allowed_connection_keys = CONNECTION_CONFIG_ALLOWLIST[config.provider_name]
        unknown_keys = set(config.connection_config) - allowed_connection_keys
        if unknown_keys:
            unknown = ", ".join(sorted(unknown_keys))
            raise ValueError(f"Unknown connection config for {config.provider_name}: {unknown}")
