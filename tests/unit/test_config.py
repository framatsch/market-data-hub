import pytest

from app.config import Settings


def _base_overrides() -> dict[str, str | bool]:
    return {
        "APP_ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    }


def test_prod_rejects_admin_auth_disabled() -> None:
    with pytest.raises(ValueError, match="ADMIN_AUTH_ENABLED=false"):
        Settings(
            **_base_overrides(),
            APP_ENV="prod",
            ADMIN_AUTH_ENABLED=False,
        )


def test_prod_rejects_missing_oidc_when_auth_enabled() -> None:
    with pytest.raises(ValueError, match="ADMIN_OIDC_ISSUER and ADMIN_OIDC_CLIENT_ID"):
        Settings(
            **_base_overrides(),
            APP_ENV="prod",
            ADMIN_AUTH_ENABLED=True,
            ADMIN_OIDC_ISSUER="",
            ADMIN_OIDC_CLIENT_ID="",
        )


def test_prod_allows_auth_enabled_with_oidc() -> None:
    settings = Settings(
        **_base_overrides(),
        APP_ENV="prod",
        ADMIN_AUTH_ENABLED=True,
        ADMIN_OIDC_ISSUER="https://auth.example",
        ADMIN_OIDC_CLIENT_ID="mdh-admin",
    )

    assert settings.APP_ENV == "prod"
    assert settings.ADMIN_AUTH_ENABLED is True


def test_dev_allows_admin_auth_disabled() -> None:
    settings = Settings(
        **_base_overrides(),
        APP_ENV="dev",
        ADMIN_AUTH_ENABLED=False,
    )

    assert settings.APP_ENV == "dev"
    assert settings.ADMIN_AUTH_ENABLED is False
