"""Append-only audit trail models (Sheet 01 Block 09, Sheet 02 footer, Sheet 06 L2, Sheet 07 N5, P5)."""
from __future__ import annotations

import hashlib
import json
import uuid
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import models

from apps.common.logging import redact_dict


class AuditEvent(models.Model):
    """Restricted append-only audit record (Sheet 01 Block 09, Sheet 02 footer, Sheet 06 L2, Sheet 07 N5)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sequence_hash = models.CharField(max_length=64, editable=False, db_index=True)
    previous_hash = models.CharField(max_length=64, blank=True, default="", editable=False)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="audit_events",
        null=True,
        blank=True,
    )
    actor_role = models.CharField(max_length=64, blank=True, default="")
    actor_scope = models.JSONField(default=dict, blank=True)
    action = models.CharField(max_length=128, db_index=True)
    target_type = models.CharField(max_length=64, db_index=True)
    target_id = models.CharField(max_length=128, db_index=True)
    case = models.ForeignKey(
        "cases.ApplicationCase",
        on_delete=models.PROTECT,
        related_name="audit_events",
        null=True,
        blank=True,
    )
    institution = models.ForeignKey(
        "organisation.Institution",
        on_delete=models.PROTECT,
        related_name="audit_events",
        null=True,
        blank=True,
    )
    region = models.ForeignKey(
        "organisation.Region",
        on_delete=models.PROTECT,
        related_name="audit_events",
        null=True,
        blank=True,
    )
    policy_version_ref = models.CharField(max_length=64, blank=True, default="")
    old_version = models.PositiveIntegerField(null=True, blank=True)
    new_version = models.PositiveIntegerField(null=True, blank=True)
    reason = models.TextField(blank=True, default="")
    inputs_snapshot = models.JSONField(default=dict, blank=True)
    correlation_id = models.CharField(max_length=64, blank=True, default="", db_index=True)

    class Meta:
        ordering = ["occurred_at", "id"]
        indexes = [
            models.Index(
                fields=["case", "occurred_at"],
                name="idx_audit_case_occurred",
            ),
            models.Index(
                fields=["target_type", "target_id"],
                name="idx_audit_target",
            ),
        ]

    def save(self, *args, **kwargs) -> None:
        """Enforce append-only immutability at the model layer in addition to DB triggers (Sheet 07 N5)."""
        if not self._state.adding and AuditEvent.objects.filter(pk=self.pk).exists():
            raise PermissionDenied("AuditEvent is append-only; UPDATE is forbidden (Sheet 07 N5).")
        self.inputs_snapshot = redact_dict(self.inputs_snapshot or {})
        payload_str = json.dumps(
            {
                "id": str(self.id),
                "previous_hash": self.previous_hash,
                "actor_id": str(self.actor_id or ""),
                "action": self.action,
                "target_type": self.target_type,
                "target_id": self.target_id,
                "old_version": self.old_version,
                "new_version": self.new_version,
                "reason": self.reason,
                "correlation_id": self.correlation_id,
            },
            sort_keys=True,
        )
        self.sequence_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):  # type: ignore[override]
        """Forbid deletion of audit records (Sheet 07 N5)."""
        raise PermissionDenied("AuditEvent is append-only; DELETE is forbidden (Sheet 07 N5).")
