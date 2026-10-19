from typing import Any


class AppError(Exception):
    """Error that maps to the API envelope {error: {code, message, details}}."""

    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None,
                 details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details or {}


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class KeysMissing(AppError):
    status_code = 412
    code = "keys_missing"


class QuotaExceeded(AppError):
    status_code = 429
    code = "quota_exceeded"


class BudgetExceeded(Exception):
    """Raised from the usage callback when a job's LLM spend would exceed its budget. Never retried."""

    def __init__(self, spent: float, budget: float):
        super().__init__(f"Job budget exceeded: spent ${spent:.4f} of ${budget:.2f}")
        self.spent = spent
        self.budget = budget


class NonRetryableError(Exception):
    """A pipeline failure that retrying the same step cannot fix (e.g. dev.to rejected the article)."""

    code = "non_retryable"


class TransientFetchError(Exception):
    """YouTube blocked or rate-limited the request. Safe to retry."""
