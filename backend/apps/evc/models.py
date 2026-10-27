"""Models for EVC readiness, slot reservation, scheduling, visits, and reports (Sheet 01 Block 03, Sheet 04 G1-G5, Sheet 07 N4, APH 1.9)."""
from __future__ import annotations

import uuid
from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class EvcMode(models.TextChoices):
    """EVC evaluation mode (APH 1.8 Note & 1.9: Online by default, Physical under extraordinary circumstances)."""

    ONLINE = "ONLINE", "Online EVC"
    PHYSICAL = "PHYSICAL", "Physical EVC"


class EvcStatus(models.TextChoices):
    """Explicit EVC coordination states (Sheet 04 G1-G5)."""

    QUEUED = "QUEUED", "Queued After Preliminary Work (G1)"
    READY = "READY", "Readiness Verified (G1)"
    SLOT_RESERVED = "SLOT_RESERVED", "Slot Reserved Atomically — Awaiting Human Confirmation (G2)"
    SCHEDULE_CONFIRMED = "SCHEDULE_CONFIRMED", "Human-Confirmed Schedule (G2/G3)"
    RESCHEDULE_REQUIRED = "RESCHEDULE_REQUIRED", "Blocker / No-Show — Controlled Rescheduling Required (G2/G4)"
    VISIT_CONDUCTED = "VISIT_CONDUCTED", "Evaluation Conducted — Awaiting Complete Report (G4)"
    REPORT_SUBMITTED = "REPORT_SUBMITTED", "Complete EVC Report Submitted — Stage Complete (G5)"
    CANCELLED = "CANCELLED", "Cancelled with Recorded Reason (G3)"


class EvcSlot(TimeStampedModel):
    """Atomic slot reservation table preventing concurrent double-booking of committees/slots (Sheet 04 G2, Sheet 07 N4)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    committee = models.ForeignKey(
        "organisation.Committee",
        on_delete=models.PROTECT,
        related_name="evc_slots",
    )
    slot_start = models.DateTimeField(db_index=True)
    slot_end = models.DateTimeField(db_index=True)
    mode = models.CharField(
        max_length=16,
        choices=EvcMode.choices,
        default=EvcMode.ONLINE,
    )
    is_reserved = models.BooleanField(default=False, db_index=True)
    reserved_by_coordination = models.OneToOneField(
        "evc.EvcCoordination",
        on_delete=models.SET_NULL,
        related_name="active_reserved_slot",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["slot_start"]
        constraints = [
            models.UniqueConstraint(
                fields=["committee", "slot_start"],
                name="uniq_evc_committee_slot_start",
            )
        ]


class EvcCoordination(TimeStampedModel):
    """EVC lifecycle record for a case stage instance (Sheet 01 Block 03, Sheet 04 G1-G5, PS Section C)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(
        "cases.ApplicationCase",
        on_delete=models.CASCADE,
        related_name="evc_coordinations",
    )
    stage_instance = models.OneToOneField(
        "cases.StageInstance",
        on_delete=models.CASCADE,
        related_name="evc_coordination",
    )
    is_new_institution_rule = models.BooleanField(default=False, db_index=True)
    mode = models.CharField(
        max_length=16,
        choices=EvcMode.choices,
        default=EvcMode.ONLINE,
    )
    status = models.CharField(
        max_length=32,
        choices=EvcStatus.choices,
        default=EvcStatus.QUEUED,
        db_index=True,
    )
    readiness_checked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="evc_readiness_checks",
        null=True,
        blank=True,
    )
    readiness_checked_at = models.DateTimeField(null=True, blank=True)
    committee = models.ForeignKey(
        "organisation.Committee",
        on_delete=models.PROTECT,
        related_name="evc_coordinations",
        null=True,
        blank=True,
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="confirmed_evc_schedules",
        null=True,
        blank=True,
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    scheduled_start = models.DateTimeField(null=True, blank=True, db_index=True)
    scheduled_end = models.DateTimeField(null=True, blank=True)
    schedule_history = models.JSONField(default=list, blank=True)
    blocker_reason = models.TextField(blank=True, default="")
    # Evaluation observations and completion records (Sheet 04 G4-G5, APH 1.9)
    observations = models.JSONField(default=dict, blank=True)
    evidence_version_ids = models.JSONField(default=list, blank=True)
    video_recording_ref = models.CharField(max_length=255, blank=True, default="")
    gps_coordinates = models.CharField(max_length=128, blank=True, default="")
    report_summary = models.TextField(blank=True, default="")
    report_submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_evc_reports",
        null=True,
        blank=True,
    )
    report_submitted_at = models.DateTimeField(null=True, blank=True)
    scheduling_deadline = models.ForeignKey(
        "deadlines.DeadlineRecord",
        on_delete=models.SET_NULL,
        related_name="evc_scheduling_coordinations",
        null=True,
        blank=True,
    )
    completion_deadline = models.ForeignKey(
        "deadlines.DeadlineRecord",
        on_delete=models.SET_NULL,
        related_name="evc_completion_coordinations",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["status", "is_new_institution_rule"],
                name="idx_evc_status_new_inst",
            ),
        ]
