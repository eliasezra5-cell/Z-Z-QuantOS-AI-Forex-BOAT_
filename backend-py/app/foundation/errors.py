"""Error types and handlers mirroring the Node foundation errors.js."""
import time

from .logger import logger


def count_error():
    try:
        from ..modules.observability.init import count_error as _ce
        _ce()
    except Exception:
        pass


class AppError(Exception):
    def __init__(self, status_code, code, message, details=None):
        super().__init__(message)
        self.statusCode = status_code
        self.code = code
        self.message = message
        self.details = details
        self.is_operational = True


class NotFoundError(AppError):
    def __init__(self, resource="Resource"):
        super().__init__(404, "NOT_FOUND", f"{resource} not found")


class ValidationError(AppError):
    def __init__(self, message, details=None):
        super().__init__(400, "VALIDATION_ERROR", message, details)


class UnauthorizedError(AppError):
    def __init__(self, message="Authentication required"):
        super().__init__(401, "UNAUTHORIZED", message)


class ForbiddenError(AppError):
    def __init__(self, message="Insufficient permissions"):
        super().__init__(403, "FORBIDDEN", message)


class ConflictError(AppError):
    def __init__(self, message):
        super().__init__(409, "CONFLICT", message)


def error_payload(err):
    if isinstance(err, AppError):
        return err.statusCode, {"error": {"code": err.code, "message": err.message, "details": err.details}}
    logger.error("[unhandled]", {"error": str(err)})
    return 500, {"error": {"code": "INTERNAL_ERROR", "message": "Internal server error"}}


def not_found_response(method, path):
    return {"error": {"code": "ROUTE_NOT_FOUND", "message": f"Route {method} {path} not found"}}
