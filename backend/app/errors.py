"""Ошибки приложения в формате, близком к RFC 9457 (problem+json)."""
from __future__ import annotations


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, details: list[dict] | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or []
        if code:
            self.code = code


class NotFound(AppError):
    status_code, code = 404, "not_found"


class Forbidden(AppError):
    status_code, code = 403, "forbidden"


class Conflict(AppError):
    status_code, code = 409, "conflict"


class ValidationFailed(AppError):
    status_code, code = 422, "validation_failed"


class ServiceUnavailable(AppError):
    status_code, code = 503, "service_unavailable"