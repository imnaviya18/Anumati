"""Tests for disabled external adapter ports (Sheet 01 Block 12, NO EXTERNAL APIs Rule)."""
from django.test import TestCase

from apps.adapters.services import AdapterNotConfiguredError, REGISTERED_PORTS


class DisabledAdaptersTests(TestCase):
    def test_all_external_ports_disabled_by_default(self) -> None:
        response = self.client.get("/api/v1/adapters/status/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["email_smtp"]["enabled"])
        self.assertEqual(payload["email_smtp"]["status"], "not_configured")
        for port_name, port_info in payload["ports"].items():
            self.assertFalse(port_info["enabled"], f"Port {port_name} must be disabled by default")
            self.assertEqual(port_info["status"], "not_configured")

    def test_invoking_disabled_port_raises_clear_error(self) -> None:
        for port in REGISTERED_PORTS.values():
            with self.assertRaisesMessage(AdapterNotConfiguredError, "not configured"):
                port.invoke({"test": "payload"})
