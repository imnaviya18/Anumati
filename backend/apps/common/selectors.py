"""Common selectors (Sheet 05)."""
from __future__ import annotations

from typing import Any

from .services import get_system_health


def select_health_snapshot() -> dict[str, Any]:
    """Return current health snapshot for health endpoint."""
    return get_system_health()
