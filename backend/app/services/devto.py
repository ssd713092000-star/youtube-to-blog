from typing import Any

import httpx

from app.core.errors import NonRetryableError

DEVTO_API = "https://dev.to/api"
_HEADERS = {"Accept": "application/vnd.forem.api-v1+json", "User-Agent": "tube2dev/1.0"}


class DevtoError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"dev.to returned {status}: {body[:300]}")
        self.status = status
        self.body = body


class DevtoRejected(NonRetryableError):
    code = "devto_rejected"


class DevtoClient:
    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None):
        self._key = api_key
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))

    def _headers(self) -> dict[str, str]:
        return {**_HEADERS, "api-key": self._key}

    async def get_me(self) -> dict[str, Any]:
        r = await self._client.get(f"{DEVTO_API}/users/me", headers=self._headers())
        if r.status_code != 200:
            raise DevtoError(r.status_code, r.text)
        return r.json()

    async def create_article(self, article: dict[str, Any]) -> dict[str, Any]:
        r = await self._client.post(f"{DEVTO_API}/articles", headers=self._headers(), json={"article": article})
        if r.status_code in (200, 201):
            return r.json()
        if 400 <= r.status_code < 500 and r.status_code != 429:
            raise DevtoRejected(f"dev.to rejected the article ({r.status_code}): {r.text[:300]}")
        raise DevtoError(r.status_code, r.text)  # 429 / 5xx -> retryable

    async def find_my_article(self, title: str, pages: int = 3) -> dict[str, Any] | None:
        """Used after a crash mid-publish: did the POST land before we could record it?"""
        for page in range(1, pages + 1):
            r = await self._client.get(
                f"{DEVTO_API}/articles/me/all", headers=self._headers(), params={"page": page, "per_page": 30}
            )
            if r.status_code != 200:
                raise DevtoError(r.status_code, r.text)
            items = r.json()
            for a in items:
                if a.get("title") == title:
                    return a
            if len(items) < 30:
                break
        return None

    async def aclose(self) -> None:
        await self._client.aclose()
