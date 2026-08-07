import base64
import binascii
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


@dataclass(frozen=True)
class EncryptedBlob:
    ciphertext: bytes
    iv: bytes
    auth_tag: bytes


class CryptoService:
    def __init__(self, encryption_key: str) -> None:
        self._key = self._decode_key(encryption_key)
        self._aesgcm = AESGCM(self._key)

    @staticmethod
    def _decode_key(encryption_key: str) -> bytes:
        if not encryption_key:
            raise ValueError("APP_ENCRYPTION_KEY is required")

        padded = encryption_key + "=" * (-len(encryption_key) % 4)
        try:
            key = base64.urlsafe_b64decode(padded.encode("ascii"))
        except (binascii.Error, UnicodeEncodeError) as exc:
            raise ValueError("APP_ENCRYPTION_KEY must be valid base64url") from exc

        if len(key) != 32:
            raise ValueError(
                "APP_ENCRYPTION_KEY must decode to exactly 32 bytes (AES-256)"
            )
        return key

    def encrypt(self, plaintext: str) -> EncryptedBlob:
        iv = os.urandom(12)
        encrypted = self._aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)
        return EncryptedBlob(
            ciphertext=encrypted[:-16],
            iv=iv,
            auth_tag=encrypted[-16:],
        )

    def decrypt(self, ciphertext: bytes, iv: bytes, auth_tag: bytes) -> str:
        try:
            plaintext = self._aesgcm.decrypt(iv, ciphertext + auth_tag, None)
        except InvalidTag as exc:
            raise ValueError("Decryption failed: authentication tag mismatch") from exc
        return plaintext.decode("utf-8")
