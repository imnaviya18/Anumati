"""Models for private versioned files, upload quarantine, and document validity registry (Sheet 01 Blocks 04/11, Sheet 03 E1, F1-F5, Sheet 07 N2, N4, P2)."""
from __future__ import annotations

import uuid
from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class QuarantineStatus(models.TextChoices):
    """Private evidence quarantine lifecycle states (Sheet 03 E1, Sheet 05, Sheet 07 P2)."""

    QUARANTINED = "QUARANTINED", "Received & Quarantined"
    SCANNING = "SCANNING", "Asynchronous Validation & Scanning"
    CLEAN = "CLEAN", "Clean (Eligible for Human Review)"
    REJECTED = "REJECTED", "Failed Validation / Scan Rejected"


class ReviewAcceptanceStatus(models.TextChoices):
    """Separate human review state (Sheet 03 E3-E4, F3-F4: Submission != Verified Fulfilment)."""

    PENDING_REVIEW = "PENDING_REVIEW", "Pending Human Review"
    ACCEPTED = "ACCEPTED", "Accepted by Authorised Reviewer"
    DEFICIENT_REJECTED = "DEFICIENT_REJECTED", "Rejected / Clarification Required by Reviewer"


class DocumentVersion(TimeStampedModel):
    """Immutable private file object version with SHA-256 checksum, quarantine state, and separate human acceptance (Sheet 01 Block 11, Sheet 03 E1, Sheet 07 N2, N4, P2)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    object_key = models.CharField(max_length=255, unique=True, db_index=True)
    institution = models.ForeignKey(
        "organisation.Institution",
        on_delete=models.PROTECT,
        related_name="document_versions",
    )
    case = models.ForeignKey(
        "cases.ApplicationCase",
        on_delete=models.PROTECT,
        related_name="document_versions",
        null=True,
        blank=True,
    )
    document_type = models.CharField(max_length=64, db_index=True)
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=128)
    size_bytes = models.PositiveBigIntegerField()
    sha256_digest = models.CharField(max_length=64, db_index=True)
    version_number = models.PositiveIntegerField(default=1)
    # Preserved original receipt time (Sheet 03 header & E1/E2)
    received_at = models.DateTimeField(db_index=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_document_versions",
    )
    quarantine_status = models.CharField(
        max_length=24,
        choices=QuarantineStatus.choices,
        default=QuarantineStatus.QUARANTINED,
        db_index=True,
    )
    scan_Finding = models.TextField(blank=True, default="")
    scanned_at = models.DateTimeField(null=True, blank=True)
    acceptance_status = models.CharField(
        max_length=24,
        choices=ReviewAcceptanceStatus.choices,
        default=ReviewAcceptanceStatus.PENDING_REVIEW,
        db_index=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviewed_document_versions",
        null=True,
        blank=True,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_finding = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-received_at"]
        indexes = [
            models.Index(
                fields=["institution", "document_type", "quarantine_status"],
                name="idx_docver_inst_type_quar",
            ),
        ]


class DownloadGrant(TimeStampedModel):
    """Short-lived, scoped download grant for clean files (Sheet 01 Block 11, Sheet 07 P1, P2, Q2)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    token = models.CharField(max_length=128, unique=True, db_index=True)
    document_version = models.ForeignKey(
        DocumentVersion,
        on_delete=models.CASCADE,
        related_name="download_grants",
    )
    issued_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="download_grants",
    )
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)


class ValidityMonitorState(models.TextChoices):
    """Document validity states (Sheet 03 F1-F5)."""

    VALID = "VALID", "Valid"
    RENEWAL_APPROACHING = "RENEWAL_APPROACHING", "Renewal Approaching"
    PENDING_RENEWAL_REVIEW = "PENDING_RENEWAL_REVIEW", "Pending Renewal Review (New Upload Awaiting Acceptance)"
    EXPIRED_OVERDUE = "EXPIRED_OVERDUE", "Expired / Overdue"


class DocumentValidityRecord(TimeStampedModel):
    """Registry of lease deeds, fire safety, building completion, structural stability, and other prescribed documents with validity dates (Sheet 03 F1-F5, PS Section E)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.ForeignKey(
        "organisation.Institution",
        on_delete=models.PROTECT,
        related_name="document_validity_records",
    )
    document_type = models.CharField(max_length=64, db_index=True)
    applicability = models.CharField(max_length=128, default="ALL_PROGRAMMES")
    accepted_version = models.ForeignKey(
        DocumentVersion,
        on_delete=models.PROTECT,
        related_name="active_validity_records",
    )
    pending_renewal_version = models.ForeignKey(
        DocumentVersion,
        on_delete=models.PROTECT,
        related_name="pending_validity_records",
        null=True,
        blank=True,
    )
    previous_accepted_versions = models.JSONField(default=list, blank=True)
    valid_from = models.DateField()
    valid_until = models.DateField(db_index=True)
    state = models.CharField(
        max_length=32,
        choices=ValidityMonitorState.choices,
        default=ValidityMonitorState.VALID,
        db_index=True,
    )
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="accepted_validity_records",
    )
    accepted_at = models.DateTimeField()
    active_deadline = models.ForeignKey(
        "deadlines.DeadlineRecord",
        on_delete=models.SET_NULL,
        related_name="validity_records",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["valid_until"]
        indexes = [
            models.Index(
                fields=["institution", "document_type", "state"],
                name="idx_docval_inst_type_state",
            ),
            models.Index(
                fields=["state", "valid_until"],
                name="idx_docval_state_until",
            ),
        ]
