"""Structured log redaction helper (Sheet 05 Operations, Sheet 07 P5)."""
from __future__ import annotations

from typing import Any

SENSITIVE_KEYS = frozenset(
    {
        "password",
        "secret",
        "token",
        "csrfmiddlewaretoken",
        "x-csrftoken",
        "authorization",
        "cookie",
        "sessionid",
    }
)


def redact_dict(payload: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive keys recursively before logging or auditing (Sheet 07 P5)."""
    sanitized: dict[str, Any] = {}
    for key, value in payload.items():
        if key.lower() in SENSITIVE_KEYS:
            sanitized[key] = "[REDACTED]"
        elif isinstance(value, dict):
            sanitized[key] = redact_dict(value)
        else:
            sanitized[key] = value
    return sanitized
