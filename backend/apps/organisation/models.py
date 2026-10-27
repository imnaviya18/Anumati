"""Models for organisation (Sheet 01, Sheet 07 N1, APH Definitions 29, 53-55, Annexure-16)."""
from __future__ import annotations

import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel


class Region(TimeStampedModel):
    """AICTE Regional Office / Regional Committee jurisdiction (Sheet 01, APH Def 29, Annexure-14)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=32, unique=True, db_index=True)
    name = models.CharField(max_length=128, unique=True)
    headquarters_city = models.CharField(max_length=128, blank=True, default="")
    states_covered = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["code"]
        indexes = [
            models.Index(fields=["code", "is_active"], name="idx_region_code_active"),
        ]

    def __str__(self) -> str:
        return f"{self.code} ({self.name})"


class Bureau(TimeStampedModel):
    """AICTE Bureau (Regulation Bureau, Approval Bureau, Policy & Academic Planning Bureau, PGRC — APH 1.8, 2.25, 7.10)."""

    class BureauType(models.TextChoices):
        REGULATION = "REGULATION", "Regulation Bureau"
        APPROVAL = "APPROVAL", "Approval Bureau"
        POLICY_ACADEMIC = "POLICY_ACADEMIC", "Policy and Academic Planning Bureau"
        PGRC = "PGRC", "Public Grievance Redressal Cell"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=32, unique=True, db_index=True)
    name = models.CharField(max_length=128)
    bureau_type = models.CharField(
        max_length=32,
        choices=BureauType.choices,
        default=BureauType.REGULATION,
        db_index=True,
    )
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} ({self.name})"


class Institution(TimeStampedModel):
    """Technical Institution / University / Applicant entity (Sheet 01, Sheet 07 N1, APH Ch. I-V)."""

    class InstitutionCategory(models.TextChoices):
        GOVERNMENT = "GOVERNMENT", "Government Institution"
        GOVERNMENT_AIDED = "GOVERNMENT_AIDED", "Government Aided Institution"
        PRIVATE_SELF_FINANCING = "PRIVATE_SELF_FINANCING", "Self-Financing Institution"
        MINORITY = "MINORITY", "Minority Institution"
        DEEMED_UNIVERSITY_GOVT = "DEEMED_UNIVERSITY_GOVT", "Institution Deemed to be University (Govt)"
        DEEMED_UNIVERSITY_PRIVATE = "DEEMED_UNIVERSITY_PRIVATE", "Institution Deemed to be University (Private)"
        STATE_PUBLIC_UNIVERSITY = "STATE_PUBLIC_UNIVERSITY", "State Public University"
        STATE_PRIVATE_UNIVERSITY = "STATE_PRIVATE_UNIVERSITY", "State Private University"
        CENTRAL_UNIVERSITY = "CENTRAL_UNIVERSITY", "Central University"
        STANDALONE_PGDM = "STANDALONE_PGDM", "Standalone Institution (PGDM/PGCM)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    permanent_id = models.CharField(max_length=64, unique=True, db_index=True)
    name = models.CharField(max_length=255, db_index=True)
    region = models.ForeignKey(
        Region,
        on_delete=models.PROTECT,
        related_name="institutions",
    )
    category = models.CharField(
        max_length=40,
        choices=InstitutionCategory.choices,
        default=InstitutionCategory.PRIVATE_SELF_FINANCING,
        db_index=True,
    )
    trust_society_company_name = models.CharField(max_length=255, blank=True, default="")
    state = models.CharField(max_length=128, db_index=True)
    district = models.CharField(max_length=128, blank=True, default="")
    city = models.CharField(max_length=128, blank=True, default="")
    address = models.TextField(blank=True, default="")
    affiliating_body = models.CharField(max_length=255, blank=True, default="")
    is_new_institution = models.BooleanField(default=False, db_index=True)
    is_women_only = models.BooleanField(default=False)
    is_pwbd_institution = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["permanent_id"]
        indexes = [
            models.Index(fields=["region", "is_active"], name="idx_inst_region_active"),
            models.Index(fields=["category", "is_new_institution"], name="idx_inst_cat_new"),
        ]

    def __str__(self) -> str:
        return f"{self.permanent_id} - {self.name}"


class Committee(TimeStampedModel):
    """Statutory / Processing Committee (Scrutiny, Re-Scrutiny, EVC, SHC, SAC, SCSC, EC, Council — APH Annexure-16)."""

    class CommitteeType(models.TextChoices):
        SCRUTINY = "SCRUTINY", "Scrutiny Committee"
        RE_SCRUTINY = "RE_SCRUTINY", "Re-Scrutiny Committee"
        EVC = "EVC", "Expert Visit Committee"
        SHC = "SHC", "Standing Hearing Committee"
        SAC = "SAC", "Standing Appellate Committee"
        SCSC = "SCSC", "Standing Complaint Scrutiny Committee"
        EXECUTIVE_COMMITTEE = "EXECUTIVE_COMMITTEE", "Executive Committee"
        COUNCIL = "COUNCIL", "The Council"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=64, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    committee_type = models.CharField(
        max_length=32,
        choices=CommitteeType.choices,
        db_index=True,
    )
    region = models.ForeignKey(
        Region,
        on_delete=models.PROTECT,
        related_name="committees",
        null=True,
        blank=True,
    )
    bureau = models.ForeignKey(
        Bureau,
        on_delete=models.PROTECT,
        related_name="committees",
        null=True,
        blank=True,
    )
    quorum_count = models.PositiveSmallIntegerField(default=2)
    valid_from = models.DateTimeField(default=timezone.now)
    valid_until = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["code"]
        indexes = [
            models.Index(fields=["committee_type", "is_active"], name="idx_comm_type_active"),
        ]

    def is_currently_valid(self, at_time: timezone.datetime | None = None) -> bool:
        """Check whether the committee is active and within its validity period (Sheet 07 N1)."""
        now = at_time or timezone.now()
        if not self.is_active:
            return False
        if self.valid_from and now < self.valid_from:
            return False
        if self.valid_until and now > self.valid_until:
            return False
        return True

    def __str__(self) -> str:
        return f"{self.code} ({self.committee_type})"


class CommitteeMembership(TimeStampedModel):
    """Validity-bounded membership of a user in a Committee (Sheet 07 N1, APH Annexure-16)."""

    class MemberRole(models.TextChoices):
        CHAIRMAN = "CHAIRMAN", "Chairman"
        ACADEMIC_EXPERT = "ACADEMIC_EXPERT", "Academician / Technical Expert"
        ADVOCATE_EXPERT = "ADVOCATE_EXPERT", "Advocate Member"
        ARCHITECT_CIVIL_EXPERT = "ARCHITECT_CIVIL_EXPERT", "Architect / Civil Engineering Expert"
        REVENUE_EXPERT = "REVENUE_EXPERT", "Revenue / Administration Member"
        REPRESENTATIVE_COOPTED = "REPRESENTATIVE_COOPTED", "Co-opted State/University Representative"
        MEMBER_SECRETARY = "MEMBER_SECRETARY", "Member Secretary"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    committee = models.ForeignKey(
        Committee,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="committee_memberships",
    )
    member_role = models.CharField(
        max_length=32,
        choices=MemberRole.choices,
        default=MemberRole.ACADEMIC_EXPERT,
    )
    valid_from = models.DateTimeField(default=timezone.now)
    valid_until = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["committee", "member_role"]
        constraints = [
            models.UniqueConstraint(
                fields=["committee", "user"],
                name="uniq_committee_user_membership",
            )
        ]

    def is_currently_valid(self, at_time: timezone.datetime | None = None) -> bool:
        """Return True if membership and parent committee are active and within validity dates."""
        now = at_time or timezone.now()
        if not self.is_active or not self.committee.is_currently_valid(now):
            return False
        if self.valid_from and now < self.valid_from:
            return False
        if self.valid_until and now > self.valid_until:
            return False
        return True
