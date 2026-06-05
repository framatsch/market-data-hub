from app.admin.crypto import CryptoService
from app.admin.key_repository import KeyRepository
from app.admin.provider_config_repository import ProviderConfigRepository
from app.config import settings


_crypto_service: CryptoService | None = None
_key_repository: KeyRepository | None = None
_provider_config_repository: ProviderConfigRepository | None = None


def initialize_admin_runtime() -> None:
    global _crypto_service, _key_repository, _provider_config_repository
    _crypto_service = CryptoService(settings.APP_ENCRYPTION_KEY)
    _key_repository = KeyRepository(settings.KEYS_DB_PATH, _crypto_service)
    _provider_config_repository = ProviderConfigRepository(settings.KEYS_DB_PATH)


def set_admin_runtime(
    crypto_service: CryptoService | None = None,
    key_repository: KeyRepository | None = None,
    provider_config_repository: ProviderConfigRepository | None = None,
) -> None:
    global _crypto_service, _key_repository, _provider_config_repository
    _crypto_service = crypto_service
    _key_repository = key_repository
    _provider_config_repository = provider_config_repository


def get_crypto_service() -> CryptoService:
    if _crypto_service is None:
        raise RuntimeError("Admin runtime is not initialized")
    return _crypto_service


def get_key_repository() -> KeyRepository:
    if _key_repository is None:
        raise RuntimeError("Admin runtime is not initialized")
    return _key_repository


def get_provider_config_repository() -> ProviderConfigRepository:
    if _provider_config_repository is None:
        raise RuntimeError("Admin runtime is not initialized")
    return _provider_config_repository
