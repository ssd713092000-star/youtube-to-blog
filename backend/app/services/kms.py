from typing import Protocol


class KeyCipher(Protocol):
    async def encrypt(self, plaintext: bytes, aad: bytes) -> tuple[bytes, str]:
        """Returns (ciphertext, key_version_name)."""
        ...

    async def decrypt(self, ciphertext: bytes, aad: bytes) -> bytes: ...


class KmsCipher:
    """Cloud KMS symmetric key via ADC. AAD binds a ciphertext to (user_id, provider), so a row copied
    to another user or provider cannot be decrypted."""

    def __init__(self, key_name: str):
        from google.cloud import kms

        if not key_name:
            raise RuntimeError("KMS_KEY_NAME is not configured")
        self._client = kms.KeyManagementServiceAsyncClient()
        self._key = key_name

    async def encrypt(self, plaintext: bytes, aad: bytes) -> tuple[bytes, str]:
        resp = await self._client.encrypt(
            request={"name": self._key, "plaintext": plaintext, "additional_authenticated_data": aad}
        )
        return resp.ciphertext, resp.name

    async def decrypt(self, ciphertext: bytes, aad: bytes) -> bytes:
        resp = await self._client.decrypt(
            request={"name": self._key, "ciphertext": ciphertext, "additional_authenticated_data": aad}
        )
        return resp.plaintext


class LocalCipher:
    """AES-256-GCM with a key from LOCAL_ENCRYPTION_KEY, for offline local development only.
    Same contract as KmsCipher (AAD-bound), so switching to KMS needs no code change."""

    def __init__(self, key_b64: str):
        import base64

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        key = base64.b64decode(key_b64) if key_b64 else b""
        if len(key) != 32:
            raise RuntimeError("LOCAL_ENCRYPTION_KEY must be a base64-encoded 32-byte key")
        self._aead = AESGCM(key)

    async def encrypt(self, plaintext: bytes, aad: bytes) -> tuple[bytes, str]:
        import os

        nonce = os.urandom(12)
        return nonce + self._aead.encrypt(nonce, plaintext, aad), "local-aesgcm-v1"

    async def decrypt(self, ciphertext: bytes, aad: bytes) -> bytes:
        return self._aead.decrypt(ciphertext[:12], ciphertext[12:], aad)
