"""Disabled external adapter port services (Sheet 01 Block 12, Sheet 05, NO EXTERNAL APIs Rule)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings


class AdapterNotConfiguredError(RuntimeError):
    """Raised when an external adapter port is invoked while disabled."""


@dataclass(frozen=True)
class DisabledAdapterPort:
    """Explicit disabled interface port for external systems (Sheet 01 Block 12)."""

    port_name: str
    source_ref: str

    def is_enabled(self) -> bool:
        """Return whether the port is configured and enabled (defaults to False)."""
        ports: dict[str, bool] = getattr(settings, "ADAPTER_PORTS", {})
        return bool(ports.get(self.port_name, False))

    def status(self) -> dict[str, Any]:
        """Return explicit port status without making network calls."""
        enabled = self.is_enabled()
        return {
            "port": self.port_name,
            "enabled": enabled,
            "status": "configured" if enabled else "not_configured",
            "source_ref": self.source_ref,
        }

    def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Refuse execution when disabled, returning clear not_configured error."""
        if not self.is_enabled():
            raise AdapterNotConfiguredError(
                f"External adapter port '{self.port_name}' is not configured (disabled by default)."
            )
        raise AdapterNotConfiguredError(
            f"External adapter port '{self.port_name}' has no live endpoint configured."
        )


REGISTERED_PORTS: dict[str, DisabledAdapterPort] = {
    "aicte_erp": DisabledAdapterPort("aicte_erp", "Sheet 01 Block 12 / Sheet 05"),
    "nsws_intake": DisabledAdapterPort("nsws_intake", "APH 1.3.1 / Sheet 02 A1"),
    "sso_identity": DisabledAdapterPort("sso_identity", "Sheet 01 Block 12 / Sheet 07 P1"),
    "payment_gateway": DisabledAdapterPort("payment_gateway", "APH 1.4.2 / Sheet 01 Block 12"),
    "sms_gateway": DisabledAdapterPort("sms_gateway", "NO EXTERNAL APIs Rule (No SMS)"),
    "external_scanner": DisabledAdapterPort("external_scanner", "Sheet 05 / OPEN_QUESTIONS OQ-2"),
}
