from app.admin.runtime import get_key_repository
from app.utils.errors import ProviderError


def get_provider_credential_sync(provider_name: str, credential_name: str) -> str:
    try:
        value = get_key_repository().get_sync(provider_name, credential_name)
    except RuntimeError as exc:
        raise ProviderError(
            f"{provider_name} credentials are unavailable.",
            code="PROVIDER_NOT_AVAILABLE",
            details={
                "provider": provider_name,
                "reason": "admin runtime not initialized",
            },
        ) from exc

    if value:
        return value

    raise ProviderError(
        f"{provider_name} credential '{credential_name}' is not configured.",
        code="PROVIDER_NOT_AVAILABLE",
        details={"provider": provider_name, "credential": credential_name},
    )
