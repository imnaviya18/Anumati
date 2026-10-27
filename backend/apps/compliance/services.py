"""Continuing obligations and evidence verification services (Sheet 01 Block 04, Sheet 03 D1-D4, E1-E4, F1-F5, Sheet 07 N2, PS Sections D & E)."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.access.models import RoleCode
from apps.access.services import resolve_actor_scope
from apps.audit.services import record_audit_event
from apps.compliance.models import EvidenceSubmission, Obligation, ObligationState
from apps.deadlines.models import ClockType, DeadlineRecord, DeadlineState
from apps.documents.models import (
    DocumentValidityRecord,
    DocumentVersion,
    QuarantineStatus,
    ReviewAcceptanceStatus,
    ValidityMonitorState,
)
from apps.outbox.models import OutboxEvent, OutboxState


@transaction.atomic
def import_pre_existing_obligation(
    *,
    actor: Any,
    institution: Any,
    source_command_ref: str,
    obligation_code: str,
    condition_text: str,
    evidence_requirement: str,
    due_at: timezone.datetime,
    verifier_role: str = RoleCode.REGIONAL_OFFICER,
    case: Any = None,
    calendar_version: str = "CAL-v1",
    reminder_offsets_hours: list[int] | None = None,
    reason: str = "Authorised import of pre-existing obligation (Sheet 03 D1)",
) -> Obligation:
    """Sheet 03 D1-D2 & PS Section D: Register pre-existing requirement only through an authorised command; create deadline and responsibility."""
    scope = resolve_actor_scope(actor)
    allowed = {RoleCode.REGIONAL_OFFICER, RoleCode.BUREAU_OFFICER, RoleCode.COMPETENT_AUTHORITY}
    if not (scope.roles & allowed):
        raise PermissionDenied(
            "Only authorised Regional/Bureau Officers or Competent Authority may import pre-existing obligations (PS Section D)."
        )
    if RoleCode.REGIONAL_OFFICER in scope.roles and institution.region_id not in scope.region_ids:
        raise PermissionDenied("Regional officer cannot import obligations outside their region.")
    if not source_command_ref or not source_command_ref.strip():
        raise ValidationError("source_command_ref is required for importing an obligation (Sheet 03 D1).")

    dl = DeadlineRecord.objects.create(
        source_type="OBLIGATION",
        source_id=institution.id,
        case=case,
        institution=institution,
        region=institution.region,
        clock_type=ClockType.INSTITUTION_SUBMISSION,
        due_at=due_at,
        calendar_version=calendar_version,
        owner_role=verifier_role,
        reminder_offsets_hours=reminder_offsets_hours if reminder_offsets_hours is not None else [168, 48, 0],
        state=DeadlineState.ACTIVE,
    )

    oblig = Obligation.objects.create(
        institution=institution,
        case=case,
        originating_decision=None,
        source_command_ref=source_command_ref.strip(),
        obligation_code=obligation_code.strip(),
        condition_text=condition_text.strip(),
        evidence_requirement=evidence_requirement.strip(),
        verifier_role=verifier_role,
        due_at=due_at,
        state=ObligationState.OPEN,
        active_deadline=dl,
    )
    dl.source_id = oblig.id
    dl.save(update_fields=["source_id"])

    record_audit_event(
        actor=actor,
        actor_role=",".join(sorted(scope.roles)),
        actor_scope=scope.to_audit_dict(),
        action="OBLIGATION_IMPORTED_AUTHORISED",
        target_type="Obligation",
        target_id=str(oblig.id),
        case=case,
        institution=institution,
        region=institution.region,
        reason=reason,
        inputs_snapshot={
            "source_command_ref": oblig.source_command_ref,
            "obligation_code": oblig.obligation_code,
            "due_at": due_at.isoformat(),
        },
    )
    return oblig


@transaction.atomic
def submit_obligation_evidence(
    *,
    actor: Any,
    obligation_id: Any,
    document_version_id: Any,
    review_sla_days: int = 7,
) -> EvidenceSubmission:
    """Sheet 03 E1-E2 & Sheet 07 N2: Record receipt of evidence for an obligation; preserve original receipt time; start separate reviewer clock once clean."""
    scope = resolve_actor_scope(actor)
    oblig = Obligation.objects.select_for_update(of=("self",)).select_related("institution", "active_deadline").get(
        pk=obligation_id
    )
    if RoleCode.INSTITUTION_USER not in scope.roles or oblig.institution_id not in scope.institution_ids:
        raise PermissionDenied("Only the responsible institution's user may submit obligation evidence (Sheet 03 E1).")

    doc_ver = DocumentVersion.objects.get(pk=document_version_id, institution=oblig.institution)
    if doc_ver.quarantine_status == QuarantineStatus.REJECTED:
        raise ValidationError("Rejected / dirty file version cannot be submitted as evidence (Sheet 03 E1, Sheet 07 Q2).")

    # Sheet 03 header & E2: Preserve original received_at time; submission lateness is evaluated against received_at
    submitted_at = doc_ver.received_at
    effective_due_at = oblig.active_deadline.due_at if oblig.active_deadline else oblig.due_at
    was_late = submitted_at > effective_due_at

    review_due = timezone.now() + timedelta(days=review_sla_days)
    submission = EvidenceSubmission.objects.create(
        obligation=oblig,
        document_version=doc_ver,
        submitted_by=actor,
        submitted_at=submitted_at,
        was_submitted_after_due=was_late,
        review_deadline_at=review_due,
    )

    oblig.state = ObligationState.EVIDENCE_SUBMITTED
    oblig.last_submitted_at = submitted_at
    oblig.is_submission_late = was_late
    oblig.save(update_fields=["state", "last_submitted_at", "is_submission_late", "updated_at"])

    # Separate reviewer clock (Sheet 01 Block 06, Sheet 03 E2/E4: Timely submission != timely verification)
    DeadlineRecord.objects.create(
        source_type="EVIDENCE_REVIEW",
        source_id=submission.id,
        case=oblig.case,
        institution=oblig.institution,
        region=oblig.institution.region,
        clock_type=ClockType.OFFICER_REVIEW,
        due_at=review_due,
        owner_role=oblig.verifier_role,
        reminder_offsets_hours=[24, 0],
        state=DeadlineState.ACTIVE,
    )

    record_audit_event(
        actor=actor,
        actor_role=RoleCode.INSTITUTION_USER,
        actor_scope=scope.to_audit_dict(),
        action="OBLIGATION_EVIDENCE_SUBMITTED",
        target_type="Obligation",
        target_id=str(oblig.id),
        case=oblig.case,
        institution=oblig.institution,
        region=oblig.institution.region,
        reason=f"Submitted evidence version {doc_ver.id}",
        inputs_snapshot={
            "submission_id": str(submission.id),
            "document_version_id": str(doc_ver.id),
            "submitted_at": submitted_at.isoformat(),
            "was_submitted_after_due": was_late,
        },
    )
    return submission


@transaction.atomic
def verify_obligation_evidence(
    *,
    actor: Any,
    submission_id: Any,
    fulfilled: bool,
    finding_notes: str,
    reviewed_at: timezone.datetime | None = None,
) -> Obligation:
    """Sheet 03 E3-E4 & Sheet 07 N2: Authorised evidence review against stated requirement.

    - Inspects exact CLEAN document version.
    - Separately records whether reviewer verification was late (Review delay remains visible — Sheet 03 E4).
    - If fulfilled: marks document version ACCEPTED, closes satisfied obligation, cancels only obsolete follow-up deadlines.
    - If not fulfilled: records deficiency, sets obligation to CLARIFICATION_REQUIRED, preserves history, queues institution notification.
    """
    scope = resolve_actor_scope(actor)
    allowed_verifiers = {
        RoleCode.REGIONAL_OFFICER,
        RoleCode.BUREAU_OFFICER,
        RoleCode.SCRUTINY_MEMBER,
        RoleCode.COMPETENT_AUTHORITY,
    }
    if not (scope.roles & allowed_verifiers):
        raise PermissionDenied("Actor is not authorised to verify obligation evidence (Sheet 03 E3).")
    if not finding_notes or not finding_notes.strip():
        raise ValidationError("Evidence verification requires recorded finding_notes (Sheet 03 E3).")

    submission = (
        EvidenceSubmission.objects.select_for_update(of=("self",))
        .select_related("obligation", "obligation__institution", "document_version")
        .get(pk=submission_id)
    )
    oblig = Obligation.objects.select_for_update().get(pk=submission.obligation_id) if submission.obligation_id else None
    if oblig is None:
        raise ValidationError("Submission is not linked to an obligation.")
    if RoleCode.REGIONAL_OFFICER in scope.roles and oblig.institution.region_id not in scope.region_ids:
        raise PermissionDenied("Regional officer cannot verify obligations outside their region.")

    from apps.access.selectors import scope_obligations_queryset
    if not scope_obligations_queryset(actor).filter(pk=oblig.pk).exists():
        raise PermissionDenied("Obligation verification is outside the actor's scope.")
    doc_ver = DocumentVersion.objects.select_for_update().get(pk=submission.document_version_id)
    if doc_ver.quarantine_status != QuarantineStatus.CLEAN:
        raise ValidationError("Cannot verify evidence before CLEAN quarantine scan completes (Sheet 03 E2-E3).")

    now = reviewed_at or timezone.now()
    review_late = bool(submission.review_deadline_at and now > submission.review_deadline_at)

    submission.reviewed_by = actor
    submission.reviewed_at = now
    submission.was_reviewed_after_review_due = review_late
    submission.is_fulfilled = fulfilled
    submission.finding_notes = finding_notes.strip()
    submission.save()

    doc_ver.acceptance_status = (
        ReviewAcceptanceStatus.ACCEPTED if fulfilled else ReviewAcceptanceStatus.DEFICIENT_REJECTED
    )
    doc_ver.reviewed_by = actor
    doc_ver.reviewed_at = now
    doc_ver.review_finding = finding_notes.strip()
    doc_ver.save()

    # Complete the reviewer clock deadline for this submission
    DeadlineRecord.objects.filter(source_type="EVIDENCE_REVIEW", source_id=submission.id).update(
        state=DeadlineState.COMPLETED
    )

    if fulfilled:
        oblig.state = ObligationState.FULFILLED
        oblig.verified_at = now
        oblig.is_verification_late = review_late
        oblig.accepted_evidence_version = doc_ver
        oblig.save()

        # Cancel only obsolete follow-up deadlines for this satisfied obligation (Sheet 03 E4)
        if oblig.active_deadline_id:
            DeadlineRecord.objects.filter(pk=oblig.active_deadline_id).update(state=DeadlineState.COMPLETED)
            OutboxEvent.objects.filter(
                deadline_id=oblig.active_deadline_id,
                state=OutboxState.PENDING,
            ).update(state=OutboxState.SUPERSEDED_CANCELLED)
    else:
        oblig.state = ObligationState.CLARIFICATION_REQUIRED
        oblig.is_verification_late = review_late
        oblig.save(update_fields=["state", "is_verification_late", "updated_at"])

        OutboxEvent.objects.create(
            logical_id=f"oblig-deficiency:{submission.id}",
            event_type="OBLIGATION_DEFICIENCY_RECORDED",
            case=oblig.case,
            payload={
                "obligation_id": str(oblig.id),
                "submission_id": str(submission.id),
                "finding_notes": finding_notes.strip(),
            },
            state=OutboxState.PENDING,
            next_attempt_at=now,
        )

    record_audit_event(
        actor=actor,
        actor_role=",".join(sorted(scope.roles)),
        actor_scope=scope.to_audit_dict(),
        action="OBLIGATION_EVIDENCE_ACCEPTED" if fulfilled else "OBLIGATION_EVIDENCE_DEFICIENT",
        target_type="Obligation",
        target_id=str(oblig.id),
        case=oblig.case,
        institution=oblig.institution,
        region=oblig.institution.region,
        reason=finding_notes.strip(),
        inputs_snapshot={
            "submission_id": str(submission.id),
            "document_version_id": str(doc_ver.id),
            "fulfilled": fulfilled,
            "was_submitted_after_due": submission.was_submitted_after_due,
            "was_reviewed_after_review_due": review_late,
        },
    )
    return oblig


@transaction.atomic
def register_accepted_validity_document(
    *,
    actor: Any,
    institution: Any,
    document_type: str,
    accepted_version_id: Any,
    valid_from: date,
    valid_until: date,
    applicability: str = "ALL_PROGRAMMES",
    reminder_offsets_hours: list[int] | None = None,
) -> DocumentValidityRecord:
    """Sheet 03 F1-F2 & PS Section E: Register an accepted document with validity dates and calculate renewal milestones."""
    scope = resolve_actor_scope(actor)
    allowed = {RoleCode.REGIONAL_OFFICER, RoleCode.BUREAU_OFFICER, RoleCode.SCRUTINY_MEMBER, RoleCode.COMPETENT_AUTHORITY}
    if not (scope.roles & allowed):
        raise PermissionDenied("Actor is not authorised to register accepted document validity (Sheet 03 F1).")
    if valid_until <= valid_from:
        raise ValidationError("valid_until must be after valid_from.")

    from apps.access.selectors import scope_documents_queryset
    doc_ver = DocumentVersion.objects.select_for_update().get(pk=accepted_version_id, institution=institution)
    if not scope_documents_queryset(actor).filter(pk=doc_ver.pk).exists():
        raise PermissionDenied("Document validity registration is outside the actor scope.")
    if doc_ver.document_type != document_type:
        raise ValidationError("Document type must match the accepted version.")
    if DocumentValidityRecord.objects.filter(accepted_version=doc_ver).exists():
        raise ValidationError("This document is already registered; use the renewal workflow.")
    if doc_ver.quarantine_status != QuarantineStatus.CLEAN:
        raise ValidationError("Document version must pass CLEAN quarantine scan before registration (Sheet 03 F1).")

    now = timezone.now()
    doc_ver.acceptance_status = ReviewAcceptanceStatus.ACCEPTED
    doc_ver.reviewed_by = actor
    doc_ver.reviewed_at = now
    doc_ver.save(update_fields=["acceptance_status", "reviewed_by", "reviewed_at", "updated_at"])

    due_dt = timezone.make_aware(timezone.datetime.combine(valid_until, timezone.datetime.min.time()))
    dl = DeadlineRecord.objects.create(
        source_type="DOCUMENT_VALIDITY",
        source_id=institution.id,
        institution=institution,
        region=institution.region,
        clock_type=ClockType.DOCUMENT_RENEWAL,
        due_at=due_dt,
        owner_role=RoleCode.REGIONAL_OFFICER,
        reminder_offsets_hours=reminder_offsets_hours if reminder_offsets_hours is not None else [720, 168, 0],
        state=DeadlineState.ACTIVE,
    )

    rec = DocumentValidityRecord.objects.create(
        institution=institution,
        document_type=document_type,
        applicability=applicability,
        accepted_version=doc_ver,
        valid_from=valid_from,
        valid_until=valid_until,
        state=ValidityMonitorState.VALID,
        accepted_by=actor,
        accepted_at=now,
        active_deadline=dl,
    )
    dl.source_id = rec.id
    dl.save(update_fields=["source_id"])

    record_audit_event(
        actor=actor,
        actor_role=",".join(sorted(scope.roles)),
        actor_scope=scope.to_audit_dict(),
        action="DOCUMENT_VALIDITY_REGISTERED",
        target_type="DocumentValidityRecord",
        target_id=str(rec.id),
        institution=institution,
        region=institution.region,
        reason=f"Registered {document_type} valid until {valid_until.isoformat()}",
        inputs_snapshot={
            "document_type": document_type,
            "accepted_version_id": str(doc_ver.id),
            "valid_from": valid_from.isoformat(),
            "valid_until": valid_until.isoformat(),
        },
    )
    return rec


@transaction.atomic
def submit_document_renewal(
    *,
    actor: Any,
    validity_record_id: Any,
    new_document_version_id: Any,
) -> DocumentValidityRecord:
    """Sheet 03 F3 & PS Section E: Submit renewal upload.

    CRITICAL RULE: 'Pending review is an explicit state. New upload cannot replace accepted validity. Wait for E3/E4 acceptance.'
    """
    scope = resolve_actor_scope(actor)
    rec = DocumentValidityRecord.objects.select_for_update(of=("self",)).select_related("institution", "accepted_version").get(
        pk=validity_record_id
    )
    if RoleCode.INSTITUTION_USER not in scope.roles or rec.institution_id not in scope.institution_ids:
        raise PermissionDenied("Only the responsible institution may submit a document renewal (Sheet 03 F3).")

    new_doc = DocumentVersion.objects.get(pk=new_document_version_id, institution=rec.institution)
    if new_doc.quarantine_status == QuarantineStatus.REJECTED:
        raise ValidationError("Rejected file version cannot be submitted for renewal.")

    rec.pending_renewal_version = new_doc
    rec.state = ValidityMonitorState.PENDING_RENEWAL_REVIEW
    rec.save(update_fields=["pending_renewal_version", "state", "updated_at"])

    EvidenceSubmission.objects.create(
        validity_record=rec,
        document_version=new_doc,
        submitted_by=actor,
        submitted_at=new_doc.received_at,
        was_submitted_after_due=new_doc.received_at.date() > rec.valid_until,
        review_deadline_at=timezone.now() + timedelta(days=7),
    )

    record_audit_event(
        actor=actor,
        actor_role=RoleCode.INSTITUTION_USER,
        actor_scope=scope.to_audit_dict(),
        action="DOCUMENT_RENEWAL_SUBMITTED_PENDING_REVIEW",
        target_type="DocumentValidityRecord",
        target_id=str(rec.id),
        institution=rec.institution,
        region=rec.institution.region,
        reason=f"Renewal upload {new_doc.id} submitted; accepted_version {rec.accepted_version_id} preserved pending human review.",
    )
    return rec


@transaction.atomic
def review_and_decide_document_renewal(
    *,
    actor: Any,
    validity_record_id: Any,
    accept: bool,
    new_valid_from: date | None,
    new_valid_until: date | None,
    finding_notes: str,
) -> DocumentValidityRecord:
    """Sheet 03 F4-F5: Accept or reject reviewed renewal.

    - If accepted (F4 -> F5): retain old version in previous_accepted_versions, record new accepted version + dates + reviewer, recalculate deadlines, supersede stale alerts.
    - If rejected: pending_renewal_version is marked DEFICIENT_REJECTED and cleared; accepted_version remains unchanged.
    """
    scope = resolve_actor_scope(actor)
    allowed = {RoleCode.REGIONAL_OFFICER, RoleCode.BUREAU_OFFICER, RoleCode.SCRUTINY_MEMBER, RoleCode.COMPETENT_AUTHORITY}
    if not (scope.roles & allowed):
        raise PermissionDenied("Actor is not authorised to accept or reject document renewals (Sheet 03 F4).")
    if not finding_notes or not finding_notes.strip():
        raise ValidationError("Renewal review requires recorded finding_notes.")

    rec = (
        DocumentValidityRecord.objects.select_for_update(of=("self",))
        .select_related("institution", "accepted_version", "pending_renewal_version", "active_deadline")
        .get(pk=validity_record_id)
    )
    from apps.access.selectors import scope_validity_records_queryset
    if not scope_validity_records_queryset(actor).filter(pk=rec.pk).exists():
        raise PermissionDenied("Renewal verification is outside the actor's scope.")
    if rec.pending_renewal_version is None:
        raise ValidationError("No pending renewal version to review on this validity record.")

    pending_doc = rec.pending_renewal_version
    if pending_doc.quarantine_status != QuarantineStatus.CLEAN:
        raise ValidationError("Pending renewal document must pass CLEAN quarantine scan before human acceptance (Sheet 03 E2/F4).")

    now = timezone.now()
    if not accept:
        pending_doc.acceptance_status = ReviewAcceptanceStatus.DEFICIENT_REJECTED
        pending_doc.reviewed_by = actor
        pending_doc.reviewed_at = now
        pending_doc.review_finding = finding_notes.strip()
        pending_doc.save()

        rec.pending_renewal_version = None
        rec.state = (
            ValidityMonitorState.EXPIRED_OVERDUE
            if now.date() > rec.valid_until
            else ValidityMonitorState.RENEWAL_APPROACHING
        )
        rec.save(update_fields=["pending_renewal_version", "state", "updated_at"])

        record_audit_event(
            actor=actor,
            actor_role=",".join(sorted(scope.roles)),
            actor_scope=scope.to_audit_dict(),
            action="DOCUMENT_RENEWAL_REJECTED",
            target_type="DocumentValidityRecord",
            target_id=str(rec.id),
            institution=rec.institution,
            region=rec.institution.region,
            reason=finding_notes.strip(),
        )
        return rec

    if not new_valid_from or not new_valid_until or new_valid_until <= new_valid_from:
        raise ValidationError("Accepted renewal requires valid new_valid_from and new_valid_until dates (Sheet 03 F4).")

    pending_doc.acceptance_status = ReviewAcceptanceStatus.ACCEPTED
    pending_doc.reviewed_by = actor
    pending_doc.reviewed_at = now
    pending_doc.review_finding = finding_notes.strip()
    pending_doc.save()

    # F4: Retain old version in history, record new accepted version, dates, and reviewer
    history = list(rec.previous_accepted_versions or [])
    history.append(
        {
            "version_id": str(rec.accepted_version_id),
            "valid_from": rec.valid_from.isoformat(),
            "valid_until": rec.valid_until.isoformat(),
            "superseded_at": now.isoformat(),
        }
    )

    # F5: Supersede old deadline & stale pending alerts, start next monitoring cycle
    if rec.active_deadline_id:
        DeadlineRecord.objects.filter(pk=rec.active_deadline_id).update(state=DeadlineState.SUPERSEDED)
        OutboxEvent.objects.filter(
            deadline_id=rec.active_deadline_id,
            state=OutboxState.PENDING,
        ).update(state=OutboxState.SUPERSEDED_CANCELLED)

    new_due_dt = timezone.make_aware(timezone.datetime.combine(new_valid_until, timezone.datetime.min.time()))
    new_dl = DeadlineRecord.objects.create(
        source_type="DOCUMENT_VALIDITY",
        source_id=rec.id,
        institution=rec.institution,
        region=rec.institution.region,
        clock_type=ClockType.DOCUMENT_RENEWAL,
        due_at=new_due_dt,
        owner_role=RoleCode.REGIONAL_OFFICER,
        reminder_offsets_hours=[720, 168, 0],
        state=DeadlineState.ACTIVE,
    )

    rec.previous_accepted_versions = history
    rec.accepted_version = pending_doc
    rec.pending_renewal_version = None
    rec.valid_from = new_valid_from
    rec.valid_until = new_valid_until
    rec.state = ValidityMonitorState.VALID
    rec.accepted_by = actor
    rec.accepted_at = now
    rec.active_deadline = new_dl
    rec.save()

    record_audit_event(
        actor=actor,
        actor_role=",".join(sorted(scope.roles)),
        actor_scope=scope.to_audit_dict(),
        action="DOCUMENT_RENEWAL_ACCEPTED",
        target_type="DocumentValidityRecord",
        target_id=str(rec.id),
        institution=rec.institution,
        region=rec.institution.region,
        reason=finding_notes.strip(),
        inputs_snapshot={
            "new_accepted_version_id": str(pending_doc.id),
            "new_valid_from": new_valid_from.isoformat(),
            "new_valid_until": new_valid_until.isoformat(),
        },
    )
    return rec
