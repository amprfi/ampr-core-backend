"""
Request logging middleware.

Provides:
- Per-request correlation ID (UUID) stored in a context variable
- Automatic request/response logging with method, path, status, and duration
- A log filter that injects the request ID into every log record
- A helper to include debug error details in 500 responses (gated by env var)
"""

import logging
import os
import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# ---------------------------------------------------------------------------
# Context variable — every log line emitted during a request can read this.
# ---------------------------------------------------------------------------
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


# ---------------------------------------------------------------------------
# Log filter: inject request_id into every LogRecord.
# Attach to a handler to get [req-abc123] in every line.
# ---------------------------------------------------------------------------

class RequestIdFilter(logging.Filter):
    """Adds a ``request_id`` attribute to every :class:`logging.LogRecord``."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get("-")  # type: ignore[attr-defined]
        return True


# ---------------------------------------------------------------------------
# Debug-error helper
# ---------------------------------------------------------------------------

_DEBUG_ERRORS: bool = os.getenv("DEBUG_ERRORS", "").lower() in ("1", "true", "yes")


def debug_detail(error: Exception) -> dict:
    """
    Return a dict suitable for ``HTTPException(detail=...)``.

    In debug mode (``DEBUG_ERRORS=true``), includes the exception type,
    message, and request ID so the frontend can surface it.

    In production, returns a generic message with just the request ID
    so the user can quote it in a support request.
    """
    rid = request_id_ctx.get("-")
    if _DEBUG_ERRORS:
        return {
            "detail": f"{type(error).__name__}: {error}",
            "error_type": type(error).__name__,
            "request_id": rid,
        }
    return {
        "detail": "Internal server error.",
        "request_id": rid,
    }


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

logger = logging.getLogger("ampr.request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that:

    1. Generates a UUID for every incoming HTTP request.
    2. Stores it in ``request_id_ctx`` so all downstream log lines are correlated.
    3. Logs method, path, status code, and elapsed time.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        rid = uuid.uuid4().hex[:8]
        token = request_id_ctx.set(rid)

        start = time.monotonic()

        # Attach request ID to request.state so route handlers can use it too
        request.state.request_id = rid

        try:
            response: Response = await call_next(request)
            elapsed = time.monotonic() - start
            level = logging.WARNING if response.status_code >= 500 else logging.INFO
            logger.log(
                level,
                "%s %s → %s (%.0fms) [req-%s]",
                request.method,
                request.url.path,
                response.status_code,
                elapsed * 1000,
                rid,
            )
            # Expose request ID in response header for client-side debugging
            response.headers["X-Request-ID"] = rid
            return response
        except Exception:
            elapsed = time.monotonic() - start
            logger.exception(
                "%s %s → 500 (%.0fms) [req-%s] unhandled exception",
                request.method,
                request.url.path,
                elapsed * 1000,
                rid,
            )
            raise
        finally:
            request_id_ctx.reset(token)
