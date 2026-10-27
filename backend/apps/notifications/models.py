"""Models for logical alerts and delivery outcomes (Sheet 04 H2-H4, Sheet 06 M6, Sheet 07 N3, N4)."""
from __future__ import annotations

import uuid
from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class DeliveryChannel(models.TextChoices):
    """Supported notification channels (in-app always; optional SMTP email; no SMS per prompt)."""

    IN_APP = "IN_APP", "In-App Notification"
    EMAIL_SMTP = "EMAIL_SMTP", "SMTP Email"


class DeliveryOutcomeState(models.TextChoices):
    """Distinct operational delivery states (Sheet 04 H4, Sheet 06 M6: Keep sent/delivered/failed/unknown distinct)."""

    PENDING = "PENDING", "Pending Dispatch"
    SENT = "SENT", "Sent / Provider Accepted"
    DELIVERED = "DELIVERED", "Delivered"
    READ = "READ", "Read by Recipient"
    FAILED = "FAILED", "Failed"
    UNKNOWN = "UNKNOWN", "Ambiguous / Unknown Outcome (Awaiting Reconciliation)"
    SUPERSEDED_CANCELLED = "SUPERSEDED_CANCELLED", "Superseded / Cancelled Before Send"


class LogicalAlert(TimeStampedModel):
    """Deduplicated logical alert identity (Sheet 04 H2, Sheet 07 N3, N4)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    deadline = models.ForeignKey(
        "deadlines.DeadlineRecord",
        on_delete=models.CASCADE,
        related_name="logical_alerts",
        null=True,
        blank=True,
    )
    deadline_revision = models.PositiveIntegerField(default=1)
    milestone_code = models.CharField(max_length=64, db_index=True)
    case = models.ForeignKey(
        "cases.ApplicationCase",
        on_delete=models.CASCADE,
        related_name="logical_alerts",
        null=True,
        blank=True,
    )
    institution = models.ForeignKey(
        "organisation.Institution",
        on_delete=models.PROTECT,
        related_name="logical_alerts",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="received_alerts",
    )
    channel = models.CharField(
        max_length=24,
        choices=DeliveryChannel.choices,
        default=DeliveryChannel.IN_APP,
    )
    subject = models.CharField(max_length=255)
    body = models.TextField()
    outcome_state = models.CharField(
        max_length=32,
        choices=DeliveryOutcomeState.choices,
        default=DeliveryOutcomeState.PENDING,
        db_index=True,
    )
    provider_receipt_id = models.CharField(max_length=128, blank=True, default="")
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Unique alert identity: deadline + revision + milestone + recipient + channel (Sheet 04 H2, Sheet 07 N3)
            models.UniqueConstraint(
                fields=["deadline", "deadline_revision", "milestone_code", "recipient", "channel"],
                condition=models.Q(deadline__isnull=False),
                name="uniq_logical_alert_identity",
            )
        ]
        indexes = [
            models.Index(
                fields=["recipient", "outcome_state", "created_at"],
                name="idx_alert_recip_state_created",
            ),
        ]
