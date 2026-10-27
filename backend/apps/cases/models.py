"""Models for versioned cases, stage instances, and deficiency cycles (Sheet 01 Block 02, Sheet 02 A1-C4, Sheet 06 K4-K6, Sheet 07 N1, N4)."""
from __future__ import annotations

import uuid
from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel
from apps.organisation.models import Bureau, Institution, Region
from apps.policy.models import PolicyVersion


class CaseStatus(models.TextChoices):
    """Explicit case lifecycle states (Sheet 02 A1-C4). Never defaults to approval."""

    DRAFT = "DRAFT", "Draft Application (A1)"
    SUBMITTED = "SUBMITTED", "Submitted / Intake Validated (A1)"
    POLICY_REVIEW_REQUIRED = "POLICY_REVIEW_REQUIRED", "Policy Route Review Required (A2)"
    IN_STAGE_PROCESSING = "IN_STAGE_PROCESSING", "In Prescribed Stage Processing (B1-B3)"
    DEFICIENCY_PENDING = "DEFICIENCY_PENDING", "Awaiting Institution Deficiency / Clarification Response (B2)"
    READY_FOR_DISPOSITION = "READY_FOR_DISPOSITION", "Ready for Competent Authority Disposition (B4/C1)"
    APPROVED_LOA = "APPROVED_LOA", "Letter of Approval Issued (C2)"
    APPROVED_EOA = "APPROVED_EOA", "Extension of Approval Issued (C2)"
    DEFICIENCY_LETTER_LOD = "DEFICIENCY_LETTER_LOD", "Letter of Deficiency Issued (C2)"
    REJECTED_LOR = "REJECTED_LOR", "Letter of Rejection / Speaking Order Issued (C2)"
    CLOSED = "CLOSED", "Processing Instance Closed (C4)"


class StageType(models.TextChoices):
    """Prescribed stage types from APH Table 2.3 and Sheet 02 B2."""

    SELF_DISCLOSURE_CHECK = "SELF_DISCLOSURE_CHECK", "Self-Disclosure Verification"
    SCRUTINY = "SCRUTINY", "Scrutiny Committee Evaluation"
    RE_SCRUTINY = "RE_SCRUTINY", "Re-Scrutiny Committee Evaluation"
    EVC = "EVC", "Expert Visit Committee (EVC) Inspection"
    SHC = "SHC", "Standing Hearing Committee (SHC)"
    SAC = "SAC", "Standing Appellate Committee (SAC)"
    SCSC = "SCSC", "Standing Complaint Scrutiny Committee (SCSC)"


class StageStatus(models.TextChoices):
    """Explicit stage instance states (Sheet 02 B1-B3)."""

    PENDING = "PENDING", "Pending / Queued"
    IN_PROGRESS = "IN_PROGRESS", "In Progress (B1/B2)"
    RETURNED_FOR_DEFICIENCY = "RETURNED_FOR_DEFICIENCY", "Returned for Deficiency / Clarification (B2)"
    COMPLETED = "COMPLETED", "Authorised Stage Completed (B3)"
    REFERRED_BACK = "REFERRED_BACK", "Referred Back by Competent Authority (C1)"
    SUPERSEDED = "SUPERSEDED", "Superseded"


class ApplicationCase(TimeStampedModel):
    """Versioned case aggregate root (Sheet 01 Block 02, Sheet 02, Sheet 06 K4, Sheet 07 N1, N4)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case_number = models.CharField(max_length=64, unique=True, db_index=True)
    source_id = models.CharField(max_length=128, unique=True, db_index=True)
    institution = models.ForeignKey(
        Institution,
        on_delete=models.PROTECT,
        related_name="cases",
    )
    region = models.ForeignKey(
        Region,
        on_delete=models.PROTECT,
        related_name="cases",
    )
    responsible_bureau = models.ForeignKey(
        Bureau,
        on_delete=models.PROTECT,
        related_name="cases",
        null=True,
        blank=True,
    )
    academic_cycle = models.CharField(max_length=32, db_index=True)
    application_category = models.CharField(max_length=64, db_index=True)
    programme_level = models.CharField(max_length=64, blank=True, default="")
    requested_courses = models.JSONField(default=list, blank=True)
    input_snapshot = models.JSONField(default=dict, blank=True)
    # Pinned policy version and route explanation (Sheet 02 A3, Sheet 07 P3)
    pinned_policy_version = models.ForeignKey(
        PolicyVersion,
        on_delete=models.PROTECT,
        related_name="pinned_cases",
        null=True,
        blank=True,
    )
    selected_route_code = models.CharField(max_length=64, blank=True, default="")
    prescribed_stages = models.JSONField(default=list, blank=True)
    route_explanation = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=32,
        choices=CaseStatus.choices,
        default=CaseStatus.DRAFT,
        db_index=True,
    )
    current_stage_type = models.CharField(
        max_length=32,
        choices=StageType.choices,
        blank=True,
        default="",
        db_index=True,
    )
    # Optimistic concurrency control version incremented on every mutation (Sheet 06 K4, L1)
    version = models.PositiveIntegerField(default=1)
    parent_case = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="linked_appeals_or_reopenings",
        null=True,
        blank=True,
    )
    submitted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["region", "status", "current_stage_type"],
                name="idx_case_region_status_stage",
            ),
            models.Index(
                fields=["institution", "academic_cycle", "status"],
                name="idx_case_inst_cycle_status",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.case_number} (v{self.version}, {self.status})"


class StageInstance(TimeStampedModel):
    """Individual execution instance of a stage, preserving repeated scrutiny/hearing history (Sheet 01 Block 02, Sheet 02 B1-B3, Sheet 07 N1)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(
        ApplicationCase,
        on_delete=models.CASCADE,
        related_name="stage_instances",
    )
    stage_type = models.CharField(
        max_length=32,
        choices=StageType.choices,
        db_index=True,
    )
    sequence_number = models.PositiveSmallIntegerField(default=1)
    iteration_number = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(
        max_length=32,
        choices=StageStatus.choices,
        default=StageStatus.PENDING,
        db_index=True,
    )
    assigned_officer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assigned_stage_instances",
        null=True,
        blank=True,
    )
    assigned_committee = models.ForeignKey(
        "organisation.Committee",
        on_delete=models.PROTECT,
        related_name="assigned_stage_instances",
        null=True,
        blank=True,
    )
    findings = models.JSONField(default=list, blank=True)
    recommendation = models.CharField(max_length=64, blank=True, default="")
    completion_reason = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="completed_stage_instances",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["case", "sequence_number", "iteration_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["case", "stage_type", "iteration_number"],
                name="uniq_case_stage_iteration",
            )
        ]
        indexes = [
            models.Index(
                fields=["case", "status"],
                name="idx_stage_case_status",
            ),
            models.Index(
                fields=["assigned_officer", "status"],
                name="idx_stage_officer_status",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.case_id}:{self.stage_type}#{self.iteration_number} ({self.status})"


class DeficiencyCycle(TimeStampedModel):
    """Deficiency / clarification cycle preserving full history of return reasons and institution responses (Sheet 01 Block 02, Sheet 02 B2)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(
        ApplicationCase,
        on_delete=models.CASCADE,
        related_name="deficiency_cycles",
    )
    stage_instance = models.ForeignKey(
        StageInstance,
        on_delete=models.CASCADE,
        related_name="deficiency_cycles",
    )
    deficiencies_recorded = models.JSONField(default=list)
    returned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="issued_deficiency_cycles",
    )
    return_reason = models.TextField()
    returned_at = models.DateTimeField(auto_now_add=True)
    institution_response = models.TextField(blank=True, default="")
    response_evidence_ids = models.JSONField(default=list, blank=True)
    responded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="responded_deficiency_cycles",
        null=True,
        blank=True,
    )
    responded_at = models.DateTimeField(null=True, blank=True)
    is_resolved = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["returned_at"]
