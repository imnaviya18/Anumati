"""Correlation ID middleware (Sheet 01 Block 01, Sheet 05 DJANGO API)."""
from __future__ import annotations

import contextvars
import uuid
from typing import Callable

from django.http import HttpRequest, HttpResponse

_correlation_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id",
    default="",
)


def get_correlation_id() -> str:
    """Return the active request/task correlation ID (Sheet 01 Block 01, 09)."""
    val = _correlation_id_ctx.get()
    if not val:
        val = str(uuid.uuid4())
        _correlation_id_ctx.set(val)
    return val


def set_correlation_id(correlation_id: str) -> None:
    """Set the active correlation ID in context."""
    _correlation_id_ctx.set(correlation_id)


class CorrelationIdMiddleware:
    """Attach X-Correlation-ID to every request and response (Sheet 01 Block 01, Sheet 05)."""

    HEADER_NAME = "HTTP_X_CORRELATION_ID"
    RESPONSE_HEADER = "X-Correlation-ID"

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        incoming = request.META.get(self.HEADER_NAME, "").strip()
        correlation_id = incoming if incoming else str(uuid.uuid4())
        set_correlation_id(correlation_id)
        request.correlation_id = correlation_id  # type: ignore[attr-defined]
        response = self.get_response(request)
        response[self.RESPONSE_HEADER] = correlation_id
        return response
