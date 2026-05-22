"""Utility for safely unwrapping pydantic SecretStr values.

Usage:
    from app.utils.secrets import unwrap_secret
    api_key = unwrap_secret(settings.FINNHUB_API_KEY)
"""


def unwrap_secret(value: object) -> str:
    """Return the plain string value of a SecretStr or a regular str.

    Works transparently with both pydantic.SecretStr and plain str so that
    call sites don't need to branch on the type.
    """
    if hasattr(value, "get_secret_value"):
        return value.get_secret_value()  # type: ignore[union-attr]
    return str(value)
