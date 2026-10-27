"""Selectors for inspecting disabled adapter ports (Sheet 01 Block 12, Sheet 05)."""
from __future__ import annotations

from typing import Any

from django.conf import settings

from .services import REGISTERED_PORTS


def select_all_adapter_statuses() -> dict[str, Any]:
    """Return status of all external adapter ports and SMTP email setting."""
    return {
        "email_smtp": {
            "enabled": bool(getattr(settings, "EMAIL_DELIVERY_ENABLED", False)),
            "status": (
                "configured"
                if getattr(settings, "EMAIL_DELIVERY_ENABLED", False)
                else "not_configured"
            ),
            "source_ref": "NO EXTERNAL APIs Rule (SMTP optional, disabled by default)",
        },
        "ports": {name: port.status() for name, port in REGISTERED_PORTS.items()},
    }
