"""Scoped selectors for audit events (Sheet 01 Block 09, Sheet 04 J6)."""
from __future__ import annotations

from typing import Any
from django.db.models import QuerySet

from apps.audit.models import AuditEvent


def select_case_audit_trail(case_id: Any) -> QuerySet[AuditEvent]:
    """Return chronological append-only audit trail for a case (Sheet 01 Block 09, PS Section B)."""
    return AuditEvent.objects.filter(case_id=case_id).order_by("occurred_at", "id")
