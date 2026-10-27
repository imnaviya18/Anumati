"""Models for access scope and role assignments (Sheet 01 Block 01, Sheet 06 K2, Sheet 07 N1, P1, P5)."""
from __future__ import annotations

import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel
from apps.organisation.models import Bureau, Committee, Institution, Region


class RoleCode(models.TextChoices):
    """Canonical 10-role matrix derived strictly from Sheets 01, 02, 04, 07 P5 and APH Annexure-16."""

    INSTITUTION_USER = "INSTITUTION_USER", "Institution Representative / Applicant"
    SCRUTINY_MEMBER = "SCRUTINY_MEMBER", "Scrutiny / Re-Scrutiny Committee Member"
    EVC_MEMBER = "EVC_MEMBER", "Expert Visit Committee Member / Chair"
    REGIONAL_OFFICER = "REGIONAL_OFFICER", "Regional Officer (RO)"
    BUREAU_OFFICER = "BUREAU_OFFICER", "Bureau Officer (Regulation / Approval / Policy / PGRC)"
    COMMITTEE_MEMBER = "COMMITTEE_MEMBER", "Standing Committee Member (SHC / SAC / SCSC)"
    COMPETENT_AUTHORITY = "COMPETENT_AUTHORITY", "Competent Authority (EC / Council / Chairman)"
    OVERSIGHT_AUDITOR = "OVERSIGHT_AUDITOR", "Oversight / Audit Official"
    POLICY_ADMIN = "POLICY_ADMIN", "Policy Governance Administrator"
    TECHNICAL_ADMIN = "TECHNICAL_ADMIN", "Technical / Operations Administrator (No Regulatory Authority)"


REGULATORY_ROLES = frozenset(
    {
        RoleCode.SCRUTINY_MEMBER,
        RoleCode.EVC_MEMBER,
        RoleCode.REGIONAL_OFFICER,
        RoleCode.BUREAU_OFFICER,
        RoleCode.COMMITTEE_MEMBER,
        RoleCode.COMPETENT_AUTHORITY,
    }
)


class RoleAssignment(TimeStampedModel):
    """Scoped, validity-bounded role assignment for a user (Sheet 01 Block 01, Sheet 07 N1, P1, P5)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="role_assignments",
    )
    role = models.CharField(
        max_length=32,
        choices=RoleCode.choices,
        db_index=True,
    )
    institution = models.ForeignKey(
        Institution,
        on_delete=models.PROTECT,
        related_name="role_assignments",
        null=True,
        blank=True,
    )
    region = models.ForeignKey(
        Region,
        on_delete=models.PROTECT,
        related_name="role_assignments",
        null=True,
        blank=True,
    )
    bureau = models.ForeignKey(
        Bureau,
        on_delete=models.PROTECT,
        related_name="role_assignments",
        null=True,
        blank=True,
    )
    committee = models.ForeignKey(
        Committee,
        on_delete=models.PROTECT,
        related_name="role_assignments",
        null=True,
        blank=True,
    )
    delegated_powers = models.JSONField(default=list, blank=True)
    valid_from = models.DateTimeField(default=timezone.now, db_index=True)
    valid_until = models.DateTimeField(null=True, blank=True, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    assigned_reason = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["user", "role", "is_active"],
                name="idx_role_assign_user_role",
            ),
            models.Index(
                fields=["institution", "is_active"],
                name="idx_role_assign_inst",
            ),
            models.Index(
                fields=["region", "is_active"],
                name="idx_role_assign_region",
            ),
        ]

    def clean(self) -> None:
        """Enforce explicit scope invariants and separation of technical vs regulatory authority (Sheet 07 N1, P5)."""
        if self.role == RoleCode.INSTITUTION_USER and not self.institution_id:
            raise ValidationError("INSTITUTION_USER assignment requires an explicit institution scope.")
        if self.role == RoleCode.REGIONAL_OFFICER and not self.region_id:
            raise ValidationError("REGIONAL_OFFICER assignment requires an explicit region scope.")
        if self.role == RoleCode.TECHNICAL_ADMIN and self.delegated_powers:
            raise ValidationError("TECHNICAL_ADMIN cannot hold delegated regulatory powers (Sheet 07 P5).")
        if self.valid_until and self.valid_from and self.valid_until <= self.valid_from:
            raise ValidationError("valid_until must be after valid_from.")

    def is_currently_valid(self, at_time: timezone.datetime | None = None) -> bool:
        """Return True if assignment is active and within [valid_from, valid_until]."""
        now = at_time or timezone.now()
        if not self.is_active:
            return False
        if self.valid_from and now < self.valid_from:
            return False
        if self.valid_until and now > self.valid_until:
            return False
        return True

    def __str__(self) -> str:
        return f"{self.user_id}:{self.role}"


class CaseAssignment(TimeStampedModel):
    """Explicit assignment of a reviewer/officer/committee to a case or stage with validity period (Sheet 01, 02 B1, 07 N1, Q2)."""

    class AssignmentScope(models.TextChoices):
        CASE_OWNER = "CASE_OWNER", "Case Owner"
        STAGE_REVIEWER = "STAGE_REVIEWER", "Stage Reviewer"
        EVC_EVALUATOR = "EVC_EVALUATOR", "EVC Evaluator"
        HEARING_COMMITTEE = "HEARING_COMMITTEE", "Hearing / Appellate Committee"
        COMPLIANCE_VERIFIER = "COMPLIANCE_VERIFIER", "Compliance / Renewal Verifier"
        ESCALATION_OWNER = "ESCALATION_OWNER", "Escalation Owner"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(
        "cases.ApplicationCase",
        on_delete=models.CASCADE,
        related_name="assignments",
    )
    stage_instance = models.ForeignKey(
        "cases.StageInstance",
        on_delete=models.CASCADE,
        related_name="assignments",
        null=True,
        blank=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="case_assignments",
        null=True,
        blank=True,
    )
    committee = models.ForeignKey(
        Committee,
        on_delete=models.PROTECT,
        related_name="case_assignments",
        null=True,
        blank=True,
    )
    assignment_scope = models.CharField(
        max_length=32,
        choices=AssignmentScope.choices,
        default=AssignmentScope.STAGE_REVIEWER,
        db_index=True,
    )
    valid_from = models.DateTimeField(default=timezone.now, db_index=True)
    valid_until = models.DateTimeField(null=True, blank=True, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    reason = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["case", "user", "is_active"],
                name="idx_case_assign_user_active",
            ),
            models.Index(
                fields=["stage_instance", "user", "is_active"],
                name="idx_stage_assign_user_active",
            ),
        ]

    def is_currently_valid(self, at_time: timezone.datetime | None = None) -> bool:
        """Check whether the case assignment is active and within its validity window."""
        now = at_time or timezone.now()
        if not self.is_active:
            return False
        if self.valid_from and now < self.valid_from:
            return False
        if self.valid_until and now > self.valid_until:
            return False
        return True
