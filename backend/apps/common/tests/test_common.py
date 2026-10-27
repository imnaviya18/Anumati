"""Tests for common app (Sheet 01 Block 01, Sheet 05)."""
from django.test import TestCase

from apps.common.logging import redact_dict


class CommonBoundaryTests(TestCase):
    def test_health_endpoint_attaches_correlation_id(self) -> None:
        response = self.client.get("/api/v1/health/", HTTP_X_CORRELATION_ID="corr-stage0-123")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["database"], "connected")
        self.assertEqual(data["correlation_id"], "corr-stage0-123")
        self.assertIn("data_as_of", data)
        self.assertEqual(response["X-Correlation-ID"], "corr-stage0-123")

    def test_log_redaction_strips_secrets(self) -> None:
        raw = {"username": "officer1", "password": "secret-password", "nested": {"token": "abc"}}
        cleaned = redact_dict(raw)
        self.assertEqual(cleaned["username"], "officer1")
        self.assertEqual(cleaned["password"], "[REDACTED]")
        self.assertEqual(cleaned["nested"]["token"], "[REDACTED]")
