"""Models for deadlines, revisions, and separate submission/review clocks (Sheet 01 Block 06, Sheet 03 D2/D4, Sheet 04 H1, Sheet 07 N3, N4)."""
from __future__ import annotations

import uuid
from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class ClockType(models.TextChoices):
    """Separate submission and review clocks (Sheet 01 Block 06, Sheet 03 E2/E4)."""

    INSTITUTION_SUBMISSION = "INSTITUTION_SUBMISSION", "Institution Submission Clock"
    OFFICER_REVIEW = "OFFICER_REVIEW", "Officer / Committee Review Clock"
    EVC_SCHEDULING = "EVC_SCHEDULING", "EVC Scheduling Clock"
    EVC_COMPLETION = "EVC_COMPLETION", "EVC Completion Clock"
    DOCUMENT_RENEWAL = "DOCUMENT_RENEWAL", "Document Validity / Renewal Clock"


class DeadlineState(models.TextChoices):
    """Durable deadline states (Sheet 04 H1)."""

    ACTIVE = "ACTIVE", "Active"
    COMPLETED = "COMPLETED", "Completed"
    SUPERSEDED = "SUPERSEDED", "Superseded"
    ON_HOLD = "ON_HOLD", "On Authorised Hold"


class DeadlineRecord(TimeStampedModel):
    """Durable due-work register record with revision history (Sheet 03 D2/D4, Sheet 04 H1, Sheet 07 N3, N4)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_type = models.CharField(max_length=32, db_index=True)
    source_id = models.UUIDField(db_index=True)
    case = models.ForeignKey(
        "cases.ApplicationCase",
        on_delete=models.CASCADE,
        related_name="deadlines",
        null=True,
        blank=True,
    )
    institution = models.ForeignKey(
        "organisation.Institution",
        on_delete=models.PROTECT,
        related_name="deadlines",
    )
    region = models.ForeignKey(
        "organisation.Region",
        on_delete=models.PROTECT,
        related_name="deadlines",
    )
    clock_type = models.CharField(
        max_length=32,
        choices=ClockType.choices,
        db_index=True,
    )
    due_at = models.DateTimeField(db_index=True)
    timezone_name = models.CharField(max_length=64, default="Asia/Kolkata")
    calendar_version = models.CharField(max_length=64, default="CAL-v1")
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_deadlines",
        null=True,
        blank=True,
    )
    owner_role = models.CharField(max_length=32, default="REGIONAL_OFFICER")
    current_revision = models.PositiveIntegerField(default=1)
    reminder_offsets_hours = models.JSONField(default=list, blank=True)
    escalation_policy_code = models.CharField(max_length=64, blank=True, default="DEFAULT")
    state = models.CharField(
        max_length=24,
        choices=DeadlineState.choices,
        default=DeadlineState.ACTIVE,
        db_index=True,
    )

    class Meta:
        ordering = ["due_at"]
        indexes = [
            models.Index(
                fields=["state", "due_at"],
                name="idx_deadline_state_due",
            ),
            models.Index(
                fields=["region", "state", "clock_type"],
                name="idx_deadline_region_state_clk",
            ),
        ]


class DeadlineRevision(TimeStampedModel):
    """Immutable history of deadline extensions or holds (Sheet 01 Block 06, Sheet 03 D4, Sheet 07 N3)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    deadline = models.ForeignKey(
        DeadlineRecord,
        on_delete=models.CASCADE,
        related_name="revisions",
    )
    revision_number = models.PositiveIntegerField()
    previous_due_at = models.DateTimeField()
    new_due_at = models.DateTimeField()
    action_type = models.CharField(max_length=32, default="EXTENSION")
    reason = models.TextField()
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approved_deadline_revisions",
    )

    class Meta:
        ordering = ["revision_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["deadline", "revision_number"],
                name="uniq_deadline_revision_number",
            )
        ]
