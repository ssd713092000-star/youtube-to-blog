"""Per-user OpenRouter and dev.to API keys, KMS-encrypted, in the separate credentials database."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, KeysMissing
from app.db.models_creds import UserCredential
from app.services.devto import DevtoClient, DevtoError
from app.services.kms import KeyCipher

Provider = Literal["openrouter", "devto"]
PROVIDERS: tuple[Provider, ...] = ("openrouter", "devto")


@dataclass
class VerifyResult:
    ok: bool
    username: str | None = None
    message: str = ""


class KeyVerifier:
    def __init__(self, http: httpx.AsyncClient | None = None):
        self._http = http or httpx.AsyncClient(timeout=15.0)

    async def verify(self, provider: Provider, api_key: str) -> VerifyResult:
        if provider == "openrouter":
            r = await self._http.get(
                "https://openrouter.ai/api/v1/key", headers={"Authorization": f"Bearer {api_key}"}
            )
            if r.status_code == 200:
                return VerifyResult(ok=True)
            return VerifyResult(ok=False, message=f"OpenRouter returned {r.status_code}")
        try:
            me = await DevtoClient(api_key, self._http).get_me()
            return VerifyResult(ok=True, username=me.get("username"))
        except DevtoError as e:
            return VerifyResult(ok=False, message=f"dev.to returned {e.status}")


def _aad(user_id: uuid.UUID, provider: str) -> bytes:
    return f"{user_id}:{provider}".encode()


class CredentialService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], cipher: KeyCipher, verifier: KeyVerifier):
        self._sessions = sessions
        self._cipher = cipher
        self._verifier = verifier

    async def status(self, user_id: uuid.UUID) -> dict[str, dict]:
        async with self._sessions() as s:
            rows = (await s.scalars(select(UserCredential).where(UserCredential.user_id == user_id))).all()
        by = {r.provider: r for r in rows}
        out: dict[str, dict] = {}
        for p in PROVIDERS:
            r = by.get(p)
            out[p] = {
                "connected": r is not None,
                "last4": r.last4 if r else None,
                "verified_at": r.verified_at if r else None,
                "status": r.status if r else "unknown",
            }
            if p == "devto":
                out[p]["username"] = r.username if r else None
        return out

    async def has_all(self, user_id: uuid.UUID) -> bool:
        st = await self.status(user_id)
        return all(st[p]["connected"] and st[p]["status"] != "invalid" for p in PROVIDERS)

    async def put(self, user_id: uuid.UUID, provider: Provider, api_key: str) -> None:
        api_key = api_key.strip()
        if len(api_key) < 8:
            raise AppError("That doesn't look like an API key.", code="invalid_key", status_code=422)
        result = await self._verifier.verify(provider, api_key)
        if not result.ok:
            raise AppError(f"Key verification failed: {result.message}", code="invalid_key", status_code=422)
        ciphertext, version = await self._cipher.encrypt(api_key.encode(), _aad(user_id, provider))
        async with self._sessions.begin() as s:
            row = await s.get(UserCredential, (user_id, provider))
            if row is None:
                row = UserCredential(user_id=user_id, provider=provider)
                s.add(row)
            row.ciphertext = ciphertext
            row.kms_key_version = version
            row.last4 = api_key[-4:]
            row.status = "ok"
            row.username = result.username
            row.verified_at = datetime.now(UTC)

    async def get_plaintext(self, user_id: uuid.UUID, provider: Provider) -> str:
        async with self._sessions() as s:
            row = await s.get(UserCredential, (user_id, provider))
        if row is None:
            raise KeysMissing(f"No {provider} API key connected.", details={"provider": provider})
        return (await self._cipher.decrypt(row.ciphertext, _aad(user_id, provider))).decode()

    async def test(self, user_id: uuid.UUID, provider: Provider) -> str:
        key = await self.get_plaintext(user_id, provider)
        result = await self._verifier.verify(provider, key)
        status = "ok" if result.ok else "invalid"
        async with self._sessions.begin() as s:
            row = await s.get(UserCredential, (user_id, provider))
            if row:
                row.status = status
                row.verified_at = datetime.now(UTC)
                if result.username:
                    row.username = result.username
        return status

    async def delete(self, user_id: uuid.UUID, provider: Provider | None = None) -> None:
        async with self._sessions.begin() as s:
            q = delete(UserCredential).where(UserCredential.user_id == user_id)
            if provider:
                q = q.where(UserCredential.provider == provider)
            await s.execute(q)
