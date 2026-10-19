from app.api import schemas
from app.core.config import Settings
from app.db.models_app import User


def user_settings(user: User, settings: Settings) -> schemas.UserSettings:
    defaults = {
        "default_model": settings.default_model,
        "default_budget_usd": settings.default_budget_usd,
    }
    return schemas.UserSettings(**{**defaults, **(user.settings or {})})
