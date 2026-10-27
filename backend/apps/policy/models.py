"""Models for policy governance (Sheet 01 Block 05, Sheet 04 J1-J3, Sheet 07 P3-P4)."""
from __future__ import annotations

import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel


class PolicyVersion(TimeStampedModel):
    """Effective-dated, versioned policy configuration governing routes, calendars, timelines, templates, and escalations (Sheet 01 Block 05, Sheet 04 J1-J3, Sheet 07 P3-P4)."""

    class PolicyState(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        VALIDATED = "VALIDATED", "Validated"
        DRY_RUN_PASSED = "DRY_RUN_PASSED", "Dry-Run Passed"
        APPROVED = "APPROVED", "Approved"
        ACTIVE = "ACTIVE", "Active"
        RETIRED = "RETIRED", "Retired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    policy_code = models.CharField(max_length=64, db_index=True)
    version_number = models.PositiveIntegerField()
    academic_cycle = models.CharField(max_length=32, db_index=True)
    state = models.CharField(
        max_length=24,
        choices=PolicyState.choices,
        default=PolicyState.DRAFT,
        db_index=True,
    )
    effective_from = models.DateTimeField(default=timezone.now, db_index=True)
    effective_until = models.DateTimeField(null=True, blank=True, db_index=True)
    calendar_version = models.CharField(max_length=64, default="CAL-v1")
    is_demonstration = models.BooleanField(default=True)
    provenance = models.JSONField(default=dict, blank=True)
    document_requirements = models.JSONField(default=dict, blank=True)
    committee_permissions = models.JSONField(default=dict, blank=True)
    exception_rules = models.JSONField(default=dict, blank=True)
    deadline_triggers = models.JSONField(default=dict, blank=True)
    # Structured, declarative policy rules (no arbitrary executable code — Sheet 07 P3)
    route_rules = models.JSONField(default=list, blank=True)
    stage_timelines = models.JSONField(default=dict, blank=True)
    evc_rules = models.JSONField(default=dict, blank=True)
    undertaking_rules = models.JSONField(default=list, blank=True)
    document_validity_rules = models.JSONField(default=dict, blank=True)
    escalation_hierarchies = models.JSONField(default=dict, blank=True)
    calendar_holidays = models.JSONField(default=list, blank=True)
    regression_cases = models.JSONField(default=list, blank=True)
    validation_report = models.JSONField(default=dict, blank=True)
    dry_run_report = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_policies",
        null=True,
        blank=True,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approved_policies",
        null=True,
        blank=True,
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_reason = models.TextField(blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-version_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["policy_code", "version_number"],
                name="uniq_policy_code_version",
            )
        ]
        indexes = [
            models.Index(
                fields=["academic_cycle", "state", "effective_from"],
                name="idx_policy_cycle_state_eff",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.policy_code}@v{self.version_number} ({self.state})"


class PolicyMigrationRecord(TimeStampedModel):
    """Explicit authorised policy migration record for open cases (Sheet 01 Block 05, Sheet 04 J3, Sheet 07 P4)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_policy = models.ForeignKey(
        PolicyVersion,
        on_delete=models.PROTECT,
        related_name="migrations_from",
    )
    target_policy = models.ForeignKey(
        PolicyVersion,
        on_delete=models.PROTECT,
        related_name="migrations_to",
    )
    authorised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="authorised_policy_migrations",
    )
    scope_filter = models.JSONField(default=dict)
    reason = models.TextField()
    affected_case_ids = models.JSONField(default=list)


class SourceRecord(TimeStampedModel):
    """Reference-only mirror; source ownership never permits regulatory state writes."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_system = models.CharField(max_length=64)
    source_id = models.CharField(max_length=128)
    payload = models.JSONField(default=dict)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["source_system", "source_id"], name="unique_sync_source_record")]


class SyncException(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_record = models.ForeignKey(SourceRecord, on_delete=models.PROTECT)
    source_system = models.CharField(max_length=64)
    event_id = models.CharField(max_length=128)
    fingerprint = models.CharField(max_length=64)
    baseline_version = models.PositiveIntegerField()
    version = models.PositiveIntegerField(default=1)
    state = models.CharField(max_length=16, default="OPEN", db_index=True)
    local_snapshot = models.JSONField(default=dict)
    incoming_snapshot = models.JSONField(default=dict)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sync_exceptions")
    reason = models.TextField()
    resolution = models.CharField(max_length=32, blank=True)
    resolution_reason = models.TextField(blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="resolved_sync_exceptions")
    resolved_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["source_system", "event_id"], name="unique_sync_source_event")]
