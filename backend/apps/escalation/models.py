"""Models for multi-level escalation tasks and ownership (Sheet 01 Block 06, Sheet 03 D3, Sheet 04 H2/H5, Sheet 06 M6, Sheet 07 N3)."""
from __future__ import annotations

import uuid
from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class EscalationState(models.TextChoices):
    """Escalation lifecycle states; remains open until closed by authorised action (Sheet 04 H5, Sheet 06 M6)."""

    OPEN = "OPEN", "Open (Owned)"
    ESCALATED_NEXT_LEVEL = "ESCALATED_NEXT_LEVEL", "Escalated to Higher Level"
    CLOSED = "CLOSED", "Closed by Authorised Action"


class EscalationTask(TimeStampedModel):
    """Multi-level escalation record with mandatory owner until closed by authorised action (Sheet 04 H2/H5, Sheet 06 M6, PS Section F)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    deadline = models.ForeignKey(
        "deadlines.DeadlineRecord",
        on_delete=models.CASCADE,
        related_name="escalations",
    )
    deadline_revision = models.PositiveIntegerField()
    case = models.ForeignKey(
        "cases.ApplicationCase",
        on_delete=models.CASCADE,
        related_name="escalations",
        null=True,
        blank=True,
    )
    institution = models.ForeignKey(
        "organisation.Institution",
        on_delete=models.PROTECT,
        related_name="escalations",
    )
    region = models.ForeignKey(
        "organisation.Region",
        on_delete=models.PROTECT,
        related_name="escalations",
    )
    escalation_level = models.PositiveSmallIntegerField(default=1, db_index=True)
    target_role = models.CharField(max_length=32)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_escalations",
    )
    trigger_reason = models.TextField()
    state = models.CharField(
        max_length=32,
        choices=EscalationState.choices,
        default=EscalationState.OPEN,
        db_index=True,
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="closed_escalations",
        null=True,
        blank=True,
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    closure_reason = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["deadline", "deadline_revision", "escalation_level"],
                name="uniq_deadline_rev_escalation_level",
            )
        ]
        indexes = [
            models.Index(
                fields=["region", "state", "escalation_level"],
                name="idx_esc_region_state_lvl",
            ),
            models.Index(
                fields=["owner", "state"],
                name="idx_esc_owner_state",
            ),
        ]
