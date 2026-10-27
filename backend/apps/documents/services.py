"""Private file storage and quarantine pipeline services (Sheet 01 Blocks 04/11, Sheet 03 E1-E4, F1-F5, Sheet 05, Sheet 07 N2, P2, Q2)."""
from __future__ import annotations

from datetime import timedelta
import hashlib
from pathlib import Path
import secrets
from typing import Any

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.access.models import RoleCode
from apps.access.selectors import scope_documents_queryset
from apps.access.services import check_case_read_access, resolve_actor_scope
from apps.audit.services import record_audit_event
from apps.documents.models import (
    DocumentVersion,
    DownloadGrant,
    QuarantineStatus,
    ReviewAcceptanceStatus,
)
from apps.outbox.models import OutboxEvent, OutboxState


# Allowed MIME types, extensions, and magic-byte file signatures (Sheet 03 E1, Sheet 07 P2, OPEN_QUESTIONS OQ-2)
ALLOWED_FILE_SIGNATURES: dict[str, tuple[tuple[str, ...], bytes]] = {
    "application/pdf": ((".pdf",), b"%PDF-"),
    "image/png": ((".png",), b"\x89PNG\r\n\x1a\n"),
    "image/jpeg": ((".jpg", ".jpeg"), b"\xff\xd8\xff"),
}


def _storage_path_for_object_key(object_key: str) -> Path:
    root = Path(settings.PRIVATE_STORAGE_ROOT).resolve()
    target = (root / object_key).resolve()
    # Path-aware containment: a plain string prefix check also accepts sibling
    # directories such as "<root>-evil" and is fragile across OS path formats.
    if not target.is_relative_to(root):
        raise PermissionDenied("Invalid storage object key path traversal rejected.")
    return target


@transaction.atomic
def receive_quarantined_upload(
    *,
    actor: Any,
    institution: Any,
    document_type: str,
    original_filename: str,
    content_type: str,
    file_bytes: bytes,
    case: Any = None,
    received_at: timezone.datetime | None = None,
) -> DocumentVersion:
    """Sheet 03 E1 & Sheet 07 P2: Save received-at time + immutable version ID, write bytes to private storage in QUARANTINED state, and queue async scan."""
    scope = resolve_actor_scope(actor)
    if RoleCode.INSTITUTION_USER in scope.roles and institution.id not in scope.institution_ids:
        raise PermissionDenied("Institution user cannot upload documents for another institution (Sheet 07 Q2).")
    if RoleCode.INSTITUTION_USER not in scope.roles:
        raise PermissionDenied("Only institution users can upload institution evidence.")
    if case is not None and case.institution_id != institution.id:
        raise ValidationError("Case institution mismatch on document upload.")

    if not file_bytes:
        raise ValidationError("Uploaded file cannot be empty.")
    max_bytes = int(getattr(settings, "MAX_UPLOAD_SIZE_BYTES", 26214400))
    if len(file_bytes) > max_bytes:
        raise ValidationError(f"Uploaded file size ({len(file_bytes)} bytes) exceeds maximum allowed ({max_bytes} bytes).")

    now = received_at or timezone.now()
    sha256_digest = hashlib.sha256(file_bytes).hexdigest()

    last_ver = (
        DocumentVersion.objects.filter(
            institution=institution,
            case=case,
            document_type=document_type,
        )
        .order_by("-version_number")
        .first()
    )
    next_ver_num = (last_ver.version_number + 1) if last_ver else 1

    safe_name = Path(original_filename).name
    object_key = f"{institution.id}/{document_type}/v{next_ver_num}_{secrets.token_hex(8)}_{safe_name}"
    file_path = _storage_path_for_object_key(object_key)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(file_bytes)

    doc_ver = DocumentVersion.objects.create(
        object_key=object_key,
        institution=institution,
        case=case,
        document_type=document_type,
        original_filename=safe_name,
        content_type=content_type,
        size_bytes=len(file_bytes),
        sha256_digest=sha256_digest,
        version_number=next_ver_num,
        received_at=now,
        uploaded_by=actor,
        quarantine_status=QuarantineStatus.QUARANTINED,
        acceptance_status=ReviewAcceptanceStatus.PENDING_REVIEW,
    )

    OutboxEvent.objects.create(
        logical_id=f"doc-scan:{doc_ver.id}",
        event_type="DOCUMENT_QUARANTINE_SCAN",
        case=case,
        payload={"document_version_id": str(doc_ver.id)},
        state=OutboxState.PENDING,
        next_attempt_at=now,
    )

    record_audit_event(
        actor=actor,
        actor_role=",".join(sorted(scope.roles)),
        actor_scope=scope.to_audit_dict(),
        action="DOCUMENT_RECEIVED_QUARANTINED",
        target_type="DocumentVersion",
        target_id=str(doc_ver.id),
        case=case,
        institution=institution,
        region=institution.region,
        new_version=next_ver_num,
        reason=f"Uploaded {document_type} v{next_ver_num}",
        inputs_snapshot={
            "document_type": document_type,
            "original_filename": safe_name,
            "size_bytes": len(file_bytes),
            "sha256_digest": sha256_digest,
            "received_at": now.isoformat(),
        },
    )
    return doc_ver


@transaction.atomic
def run_quarantine_scan(
    *,
    document_version_id: Any,
    simulate_scanner_outage: bool = False,
) -> DocumentVersion:
    """Sheet 03 E1, Sheet 05, Sheet 07 P2, Q2: Validate file type, extension, size, checksum, and magic-byte signature.

    - Scanner outage leaves file in QUARANTINED (Pending scan is not rejection — Sheet 03 E1, Sheet 07 P2).
    - Validation/signature mismatch marks file REJECTED.
    - Valid signature marks file CLEAN, preserving original received_at time (Sheet 03 E2).
    """
    doc = DocumentVersion.objects.select_for_update().get(pk=document_version_id)
    if doc.quarantine_status in (QuarantineStatus.CLEAN, QuarantineStatus.REJECTED):
        return doc

    if simulate_scanner_outage:
        doc.quarantine_status = QuarantineStatus.QUARANTINED
        doc.scan_Finding = "Scanner unavailable; file retained in quarantine (Sheet 03 E1 / Sheet 07 P2)."
        doc.save(update_fields=["quarantine_status", "scan_Finding", "updated_at"])
        return doc

    doc.quarantine_status = QuarantineStatus.SCANNING
    doc.save(update_fields=["quarantine_status", "updated_at"])

    file_path = _storage_path_for_object_key(doc.object_key)
    if not file_path.is_file():
        doc.quarantine_status = QuarantineStatus.QUARANTINED
        doc.scan_Finding = "Storage object missing during scan; retained in quarantine."
        doc.save(update_fields=["quarantine_status", "scan_Finding", "updated_at"])
        return doc

    raw_bytes = file_path.read_bytes()
    actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    now = timezone.now()

    if actual_sha256 != doc.sha256_digest:
        doc.quarantine_status = QuarantineStatus.REJECTED
        doc.scan_Finding = "SHA-256 checksum mismatch."
        doc.scanned_at = now
        doc.save(update_fields=["quarantine_status", "scan_Finding", "scanned_at", "updated_at"])
        return doc

    spec = ALLOWED_FILE_SIGNATURES.get(doc.content_type)
    ext = Path(doc.original_filename).suffix.lower()
    if not spec:
        doc.quarantine_status = QuarantineStatus.REJECTED
        doc.scan_Finding = f"Unsupported content type '{doc.content_type}'."
        doc.scanned_at = now
        doc.save(update_fields=["quarantine_status", "scan_Finding", "scanned_at", "updated_at"])
        return doc

    allowed_exts, magic_prefix = spec
    if ext not in allowed_exts or not raw_bytes.startswith(magic_prefix):
        doc.quarantine_status = QuarantineStatus.REJECTED
        doc.scan_Finding = f"File extension '{ext}' or magic-byte signature invalid for '{doc.content_type}'."
        doc.scanned_at = now
        doc.save(update_fields=["quarantine_status", "scan_Finding", "scanned_at", "updated_at"])
        return doc

    doc.quarantine_status = QuarantineStatus.CLEAN
    doc.scan_Finding = "File signature, extension, size, and SHA-256 verified clean."
    doc.scanned_at = now
    doc.save(update_fields=["quarantine_status", "scan_Finding", "scanned_at", "updated_at"])
    return doc


@transaction.atomic
def issue_short_lived_download_grant(
    *,
    actor: Any,
    document_version_id: Any,
    ttl_seconds: int = 300,
) -> DownloadGrant:
    """Sheet 01 Block 11, Sheet 07 P1, P2, Q2: Issue a short-lived download grant after verifying scope and CLEAN quarantine state."""
    doc = DocumentVersion.objects.select_related("institution", "case").get(pk=document_version_id)

    # 1. Verify actor scope on document / case (Sheet 07 P1, Q2)
    if doc.case is not None:
        check_case_read_access(actor, doc.case)
    else:
        if not scope_documents_queryset(actor, DocumentVersion.objects.filter(pk=doc.pk)).exists():
            raise PermissionDenied("Cross-institution or unauthorized document download denied (Sheet 07 Q2).")

    # 2. Quarantined or rejected ("dirty") files are unavailable for download (Sheet 07 Q2)
    if doc.quarantine_status != QuarantineStatus.CLEAN:
        raise PermissionDenied(
            f"Document version is '{doc.quarantine_status}' and unavailable for download (Sheet 07 P2, Q2)."
        )

    token = secrets.token_urlsafe(32)
    grant = DownloadGrant.objects.create(
        token=token,
        document_version=doc,
        issued_to=actor,
        expires_at=timezone.now() + timedelta(seconds=ttl_seconds),
    )
    return grant


@transaction.atomic
def redeem_download_grant(*, actor: Any, token: str, now: timezone.datetime | None = None) -> tuple[DocumentVersion, bytes]:
    """Redeem a short-lived download grant and return verified file bytes (Sheet 01 Block 11, Sheet 07 P2, Q2)."""
    current_time = now or timezone.now()
    grant = DownloadGrant.objects.select_for_update(of=("self",)).select_related("document_version").filter(token=token).first()
    if grant is None:
        raise PermissionDenied("Invalid download grant token.")
    if grant.issued_to_id != getattr(actor, "pk", None):
        raise PermissionDenied("Download grant belongs to a different user (Sheet 07 P1, Q2).")
    if current_time > grant.expires_at:
        raise PermissionDenied("Short-lived download grant has expired (Sheet 07 P2).")
    doc = grant.document_version
    if doc.quarantine_status != QuarantineStatus.CLEAN:
        raise PermissionDenied("Document is not CLEAN; download denied (Sheet 07 Q2).")

    file_path = _storage_path_for_object_key(doc.object_key)
    raw_bytes = file_path.read_bytes()
    if hashlib.sha256(raw_bytes).hexdigest() != doc.sha256_digest:
        raise ValidationError("Stored file checksum mismatch detected.")

    grant.used_at = current_time
    grant.save(update_fields=["used_at", "updated_at"])
    return doc, raw_bytes


@transaction.atomic
def review_and_accept_document_version(
    *,
    actor: Any,
    document_version_id: Any,
    accept: bool,
    finding: str,
) -> DocumentVersion:
    """Sheet 03 E3-E4, Sheet 07 P2, Q2: Human compliance/evidence acceptance is separate from quarantine scanning."""
    scope = resolve_actor_scope(actor)
    allowed_reviewers = {
        RoleCode.SCRUTINY_MEMBER,
        RoleCode.EVC_MEMBER,
        RoleCode.REGIONAL_OFFICER,
        RoleCode.BUREAU_OFFICER,
        RoleCode.COMMITTEE_MEMBER,
        RoleCode.COMPETENT_AUTHORITY,
    }
    if not (scope.roles & allowed_reviewers):
        raise PermissionDenied("Actor is not authorised to review and accept evidence versions (Sheet 03 E3).")
    if not finding or not finding.strip():
        raise ValidationError("Evidence review requires a recorded finding (Sheet 03 E3).")

    doc = DocumentVersion.objects.select_for_update(of=("self",)).select_related("institution", "case").get(pk=document_version_id)
    if doc.case is not None:
        check_case_read_access(actor, doc.case)
    elif not scope_documents_queryset(actor).filter(pk=doc.pk).exists():
        raise PermissionDenied("Regional officer cannot review documents outside their region.")

    if doc.quarantine_status != QuarantineStatus.CLEAN:
        raise ValidationError("Cannot accept or review a document version that has not passed a CLEAN scan (Sheet 03 E2-E3).")

    doc.acceptance_status = (
        ReviewAcceptanceStatus.ACCEPTED if accept else ReviewAcceptanceStatus.DEFICIENT_REJECTED
    )
    doc.reviewed_by = actor
    doc.reviewed_at = timezone.now()
    doc.review_finding = finding.strip()
    doc.save(
        update_fields=[
            "acceptance_status",
            "reviewed_by",
            "reviewed_at",
            "review_finding",
            "updated_at",
        ]
    )

    record_audit_event(
        actor=actor,
        actor_role=",".join(sorted(scope.roles)),
        actor_scope=scope.to_audit_dict(),
        action="DOCUMENT_VERSION_ACCEPTED" if accept else "DOCUMENT_VERSION_REJECTED",
        target_type="DocumentVersion",
        target_id=str(doc.id),
        case=doc.case,
        institution=doc.institution,
        region=doc.institution.region,
        new_version=doc.version_number,
        reason=finding.strip(),
        inputs_snapshot={
            "document_version_id": str(doc.id),
            "accept": accept,
            "sha256_digest": doc.sha256_digest,
        },
    )
    return doc


def validate_case_evidence(*, actor, case, evidence_ids, accepted=False):
    """Bind findings to accessible exact versions, never another case's files."""
    from django.db.models import Q
    if not isinstance(evidence_ids, list) or any(not isinstance(value, str) for value in evidence_ids):
        raise ValidationError("Evidence references must be a list of version IDs.")
    qs = scope_documents_queryset(actor).filter(
        Q(case=case) | Q(case__isnull=True), institution_id=case.institution_id,
        id__in=evidence_ids, quarantine_status=QuarantineStatus.CLEAN,
    )
    if accepted:
        qs = qs.filter(acceptance_status=ReviewAcceptanceStatus.ACCEPTED)
    if qs.count() != len(set(evidence_ids)):
        raise ValidationError("Evidence must be clean, accessible and linked to this case or its institution's shared documents.")
