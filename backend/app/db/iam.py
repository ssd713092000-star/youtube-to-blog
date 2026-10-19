"""Cloud SQL IAM database authentication without a sidecar.

On Cloud Run the built-in /cloudsql socket doesn't log IAM users in automatically, so with
DB_IAM_AUTH=true every new connection uses a short-lived OAuth token from ADC (the service's own
service account) as its password. Locally, the Auth Proxy's --auto-iam-authn does this instead.
"""

import asyncio
import time

import psycopg

_SCOPES = ["https://www.googleapis.com/auth/sqlservice.login"]
_lock = asyncio.Lock()
_cache: dict[str, float | str] = {"token": "", "exp": 0.0}


async def iam_token() -> str:
    async with _lock:
        if _cache["token"] and float(_cache["exp"]) - time.time() > 300:
            return str(_cache["token"])

        def _refresh() -> tuple[str, float]:
            import google.auth
            from google.auth.transport.requests import Request

            creds, _ = google.auth.default(scopes=_SCOPES)
            creds.refresh(Request())
            exp = creds.expiry.timestamp() if creds.expiry else time.time() + 3000
            return creds.token, exp

        token, exp = await asyncio.to_thread(_refresh)
        _cache.update(token=token, exp=exp)
        return token


class IamAsyncConnection(psycopg.AsyncConnection):
    """psycopg connection class that injects a fresh IAM token as the password."""

    @classmethod
    async def connect(cls, conninfo: str = "", **kwargs):  # type: ignore[override]
        kwargs["password"] = await iam_token()
        return await super().connect(conninfo, **kwargs)


def connection_class(iam_auth: bool) -> type[psycopg.AsyncConnection]:
    return IamAsyncConnection if iam_auth else psycopg.AsyncConnection
