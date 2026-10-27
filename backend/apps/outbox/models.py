"""Models for durable outbox events, leases, delivery attempts, and failed-job owner queue (Sheet 01 Block 08, Sheet 05, Sheet 06 L2/L4, M1-M6, Sheet 07 N4)."""
from __future__ import annotations

import uuid
from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class OutboxState(models.TextChoices):
    """Durable outbox lifecycle states (Sheet 06 L4, M1-M6)."""

    PENDING = "PENDING", "Pending Dispatch"
    LEASED = "LEASED", "Leased by Dispatcher / Worker"
    PUBLISHED = "PUBLISHED", "Published to Broker (Awaiting Worker Completion)"
    COMPLETED = "COMPLETED", "Completed"
    SUPERSEDED_CANCELLED = "SUPERSEDED_CANCELLED", "Superseded / Cancelled"
    FAILED_OWNED = "FAILED_OWNED", "Retry Exhausted / Permanent Failure (Assigned to Owner)"
    UNKNOWN_RECONCILING = "UNKNOWN_RECONCILING", "Ambiguous Outcome Awaiting Reconciliation"


class OutboxEvent(TimeStampedModel):
    """PostgreSQL durable outbox event committed atomically with business state (Sheet 06 L2, L4, M1-M6, Sheet 07 N4)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    logical_id = models.CharField(max_length=128, unique=True, db_index=True)
    event_type = models.CharField(max_length=64, db_index=True)
    case = models.ForeignKey(
        "cases.ApplicationCase",
        on_delete=models.CASCADE,
        related_name="outbox_events",
        null=True,
        blank=True,
    )
    case_version = models.PositiveIntegerField(null=True, blank=True)
    deadline = models.ForeignKey(
        "deadlines.DeadlineRecord",
        on_delete=models.CASCADE,
        related_name="outbox_events",
        null=True,
        blank=True,
    )
    deadline_revision = models.PositiveIntegerField(null=True, blank=True)
    payload = models.JSONField(default=dict)
    state = models.CharField(
        max_length=32,
        choices=OutboxState.choices,
        default=OutboxState.PENDING,
        db_index=True,
    )
    lease_owner = models.CharField(max_length=128, blank=True, default="")
    lease_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    next_attempt_at = models.DateTimeField(db_index=True)
    last_error = models.TextField(blank=True, default="")
    # Failed-job owner queue assignment (Sheet 04 J4-J5, Sheet 06 M3, M5)
    exception_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_outbox_exceptions",
        null=True,
        blank=True,
    )
    exception_reason = models.TextField(blank=True, default="")
    correlation_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["next_attempt_at", "created_at"]
        indexes = [
            models.Index(
                fields=["state", "next_attempt_at"],
                name="idx_outbox_state_next_att",
            ),
            models.Index(
                fields=["state", "lease_expires_at"],
                name="idx_outbox_state_lease_exp",
            ),
        ]


class DeliveryAttempt(TimeStampedModel):
    """Individual bounded external/worker execution attempt record (Sheet 06 M2-M4, Sheet 07 N3)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    outbox_event = models.ForeignKey(
        OutboxEvent,
        on_delete=models.CASCADE,
        related_name="attempts",
    )
    attempt_number = models.PositiveSmallIntegerField()
    worker_id = models.CharField(max_length=128)
    outcome = models.CharField(max_length=32, db_index=True)
    provider_receipt = models.CharField(max_length=128, blank=True, default="")
    error_detail = models.TextField(blank=True, default="")
    correlation_id = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        ordering = ["attempt_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["outbox_event", "attempt_number"],
                name="uniq_outbox_event_attempt_num",
            )
        ]


class CallbackReceipt(TimeStampedModel):
    """Deduplicated external callback receipt for reconciling ambiguous outcomes (Sheet 05, Sheet 06 M4, Sheet 07 N4, P4)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    external_event_id = models.CharField(max_length=128, unique=True, db_index=True)
    outbox_event = models.ForeignKey(
        OutboxEvent,
        on_delete=models.CASCADE,
        related_name="callbacks",
    )
    reported_status = models.CharField(max_length=32)
    raw_payload = models.JSONField(default=dict)
