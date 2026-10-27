"""Models for continuing obligations, evidence submissions, and verification findings (Sheet 01 Block 04, Sheet 03 D1-D4, E1-E4, Sheet 07 N2)."""
from __future__ import annotations

import uuid
from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class ObligationState(models.TextChoices):
    """Independent lifecycle state of a continuing obligation (Sheet 02 C3-C4, Sheet 03 D1-D4, E4)."""

    OPEN = "OPEN", "Open / Monitoring"
    EVIDENCE_SUBMITTED = "EVIDENCE_SUBMITTED", "Evidence Submitted (Pending Scan / Review)"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED", "Deficiency Recorded / Clarification Required"
    FULFILLED = "FULFILLED", "Verified & Fulfilled"
    ON_HOLD = "ON_HOLD", "Authorised Hold"


class Obligation(TimeStampedModel):
    """Continuing obligation / undertaking linked to originating decision or authorised import command (Sheet 03 D1, Sheet 07 N2, PS Section D)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.ForeignKey(
        "organisation.Institution",
        on_delete=models.PROTECT,
        related_name="obligations",
    )
    case = models.ForeignKey(
        "cases.ApplicationCase",
        on_delete=models.PROTECT,
        related_name="obligations",
        null=True,
        blank=True,
    )
    originating_decision = models.ForeignKey(
        "decisions.CaseDecision",
        on_delete=models.PROTECT,
        related_name="created_obligations",
        null=True,
        blank=True,
    )
    source_command_ref = models.CharField(max_length=128)
    obligation_code = models.CharField(max_length=64, db_index=True)
    condition_text = models.TextField()
    evidence_requirement = models.TextField()
    verifier_role = models.CharField(max_length=32, default="REGIONAL_OFFICER")
    due_at = models.DateTimeField(db_index=True)
    state = models.CharField(
        max_length=32,
        choices=ObligationState.choices,
        default=ObligationState.OPEN,
        db_index=True,
    )
    # Submission, verification, and lateness stored as separate facts (Sheet 03 header, Sheet 07 N2, PS D)
    last_submitted_at = models.DateTimeField(null=True, blank=True)
    is_submission_late = models.BooleanField(default=False, db_index=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    is_verification_late = models.BooleanField(default=False, db_index=True)
    accepted_evidence_version = models.ForeignKey(
        "documents.DocumentVersion",
        on_delete=models.PROTECT,
        related_name="satisfied_obligations",
        null=True,
        blank=True,
    )
    active_deadline = models.ForeignKey(
        "deadlines.DeadlineRecord",
        on_delete=models.SET_NULL,
        related_name="obligations",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["due_at"]
        indexes = [
            models.Index(
                fields=["institution", "state", "due_at"],
                name="idx_oblig_inst_state_due",
            ),
        ]


class EvidenceSubmission(TimeStampedModel):
    """Link between an obligation/renewal and an immutable DocumentVersion with reviewer finding (Sheet 03 E1-E4, Sheet 07 N2)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    obligation = models.ForeignKey(
        Obligation,
        on_delete=models.CASCADE,
        related_name="submissions",
        null=True,
        blank=True,
    )
    validity_record = models.ForeignKey(
        "documents.DocumentValidityRecord",
        on_delete=models.CASCADE,
        related_name="renewal_submissions",
        null=True,
        blank=True,
    )
    document_version = models.ForeignKey(
        "documents.DocumentVersion",
        on_delete=models.PROTECT,
        related_name="evidence_submissions",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="evidence_submissions",
    )
    submitted_at = models.DateTimeField(db_index=True)
    was_submitted_after_due = models.BooleanField(default=False)
    review_deadline_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviewed_evidence_submissions",
        null=True,
        blank=True,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    was_reviewed_after_review_due = models.BooleanField(default=False)
    is_fulfilled = models.BooleanField(null=True, blank=True)
    finding_notes = models.TextField(blank=True, default="")
