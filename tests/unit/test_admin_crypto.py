import base64
import os

import pytest

from app.admin.crypto import CryptoService


def _key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def test_crypto_service_round_trip() -> None:
    crypto = CryptoService(_key())

    blob = crypto.encrypt("secret-api-key")

    assert crypto.decrypt(blob.ciphertext, blob.iv, blob.auth_tag) == "secret-api-key"
    assert b"secret-api-key" not in blob.ciphertext


def test_crypto_service_rejects_tampered_ciphertext() -> None:
    crypto = CryptoService(_key())
    blob = crypto.encrypt("secret-api-key")
    tampered = bytearray(blob.ciphertext)
    tampered[0] ^= 1

    with pytest.raises(ValueError, match="authentication tag mismatch"):
        crypto.decrypt(bytes(tampered), blob.iv, blob.auth_tag)


def test_crypto_service_uses_distinct_iv_per_encrypt_call() -> None:
    crypto = CryptoService(_key())

    first = crypto.encrypt("same-secret")
    second = crypto.encrypt("same-secret")

    assert first.iv != second.iv


def test_crypto_service_requires_32_byte_key() -> None:
    short_key = base64.urlsafe_b64encode(b"short").decode()

    with pytest.raises(ValueError, match="exactly 32 bytes"):
        CryptoService(short_key)
