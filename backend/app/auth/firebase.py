"""Firebase Auth (Identity Platform) ID-token verification. firebase-admin uses ADC; verifying an ID
token only needs the project id and Google's public certs (cached by the SDK)."""

import logging
from dataclasses import dataclass

from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.errors import AppError

log = logging.getLogger(__name__)


@dataclass
class Identity:
    uid: str
    email: str | None
    name: str | None
    picture: str | None


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


class TokenVerifier:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._app = None
        if settings.auth_mode == "firebase":
            import firebase_admin

            opts = {"projectId": settings.firebase_project_id or settings.gcp_project}
            try:
                self._app = firebase_admin.get_app()
            except ValueError:
                self._app = firebase_admin.initialize_app(options=opts)

    async def verify(self, token: str) -> Identity:
        if self._settings.auth_mode == "dev":
            # Local only (enforced in Settings.assert_safe): "Bearer dev:alice@example.com"
            if not token.startswith("dev:") or "@" not in token:
                raise Unauthorized("Dev auth expects 'Bearer dev:<email>'.")
            email = token[4:]
            return Identity(uid=f"dev-{email}", email=email, name=email.split("@")[0], picture=None)

        from firebase_admin import auth

        try:
            claims = await run_in_threadpool(auth.verify_id_token, token, self._app)
        except (auth.ExpiredIdTokenError, auth.RevokedIdTokenError):
            raise Unauthorized("Session expired.", code="token_expired") from None
        except Exception:
            raise Unauthorized("Invalid credentials.") from None
        return Identity(uid=claims["uid"], email=claims.get("email"), name=claims.get("name"),
                        picture=claims.get("picture"))

    async def delete_user(self, uid: str) -> None:
        if self._settings.auth_mode != "firebase":
            return
        from firebase_admin import auth

        try:
            await run_in_threadpool(auth.delete_user, uid, self._app)
        except Exception:
            log.exception("could not delete Firebase user")
