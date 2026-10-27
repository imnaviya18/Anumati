"""Guarded decision and transition command services (Sheet 06 K1-K6, L1-L3, Sheet 02 B3, C2)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.access.models import RoleCode
from apps.access.services import (
    check_case_read_access,
    check_stage_execution_access,
    resolve_actor_scope,
)
from apps.audit.services import record_audit_event
from apps.cases.models import ApplicationCase, CaseStatus, StageInstance, StageStatus, StageType
from apps.common.middleware import get_correlation_id
from apps.compliance.models import Obligation, ObligationState
from apps.deadlines.models import ClockType, DeadlineRecord, DeadlineState
from apps.decisions.models import CaseDecision, DecisionOutcome, IdempotencyRecord
from apps.outbox.models import OutboxEvent, OutboxState
from apps.routing.services import TransitionViolationError, validate_case_transition


class StaleCaseVersionError(Exception):
    """Raised when expected_version does not match locked Case.version (HTTP 409 — Sheet 06 K4)."""


class IdempotencyConflictError(Exception):
    """Raised when an Idempotency-Key is reused with a different payload fingerprint (HTTP 409 — Sheet 06 K3)."""


@dataclass(frozen=True)
class CommandExecutionResult:
    """Result returned by a guarded decision or stage transition command (Sheet 06 K3, L3)."""

    status_code: int
    body: dict[str, Any]
    replayed: bool = False


def compute_payload_fingerprint(payload: dict[str, Any]) -> str:
    """Compute canonical SHA-256 fingerprint of a command payload (Sheet 06 K1, K3)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _resolve_or_replay_command(
    *,
    actor: Any,
    action: str,
    idempotency_key: str,
    payload_fingerprint: str,
    case_for_access_check: ApplicationCase,
) -> IdempotencyRecord | None:
    """Check if (actor, action, idempotency_key) already exists (Sheet 06 K2, K3).

    - Replayed responses also require current access (Sheet 06 K2).
    - Same key + same payload returns committed result; different payload -> conflict (Sheet 06 K3).
    """
    existing = IdempotencyRecord.objects.filter(
        actor=actor,
        action=action,
        idempotency_key=idempotency_key,
    ).first()
    if not existing:
        return None

    # Sheet 06 K2: Replayed responses also require current access
    check_case_read_access(actor, case_for_access_check)
    if existing.payload_fingerprint != payload_fingerprint:
        raise IdempotencyConflictError(
            f"Idempotency key '{idempotency_key}' was already used with a different payload (Sheet 06 K3)."
        )
    return existing


@transaction.atomic
def execute_guarded_decision_command(
    *,
    actor: Any,
    case_id: Any,
    action: str,
    expected_version: int,
    idempotency_key: str,
    outcome: str,
    reasons: str,
    delegated_power_ref: str,
    reviewed_evidence_version_ids: list[str] | None = None,
    refer_back_stage_type: str = "",
    obligations_spec: list[dict[str, Any]] | None = None,
) -> CommandExecutionResult:
    """Execute a Competent Authority disposition command (Sheet 02 C1-C3, Sheet 06 K1-K6, L1-L3).

    Single PostgreSQL transaction; no network calls inside:
    - K1: Receive command + payload fingerprint
    - K2: Authenticate & check scope (rechecked under lock)
    - K3: Resolve command identity (same key + same payload replays; different payload conflicts)
    - K4: Lock case aggregate row (`select_for_update()`) & check expected_version (stale -> 409)
    - K5: Validate transition under lock (required stages, accepted evidence, authority, pinned policy)
    - K6 / L1: Write decision + reasons + evidence refs, advance case/stage & increment version, create obligations & deadlines
    - L2: Append audit event + durable outbox event + idempotency response
    - L3: Commit atomically and return committed outcome
    """
    if not idempotency_key or not idempotency_key.strip():
        raise ValidationError("idempotency_key is required for guarded decision commands (Sheet 06 K1).")
    if not reasons or not reasons.strip():
        raise ValidationError("Authorised decision requires explicit recorded reasons (Sheet 02 C2).")

    payload_for_hash = {
        "case_id": str(case_id),
        "action": action,
        "expected_version": expected_version,
        "outcome": outcome,
        "reasons": reasons.strip(),
        "delegated_power_ref": delegated_power_ref.strip(),
        "reviewed_evidence_version_ids": sorted(reviewed_evidence_version_ids or []),
        "refer_back_stage_type": refer_back_stage_type,
        "obligations_spec": obligations_spec or [],
    }
    fingerprint = compute_payload_fingerprint(payload_for_hash)

    # K4: Lock case row in consistent order before checking replay/version
    locked_case = ApplicationCase.objects.select_for_update().get(pk=case_id)

    # K3: Check command identity under lock
    replayed_record = _resolve_or_replay_command(
        actor=actor,
        action=action,
        idempotency_key=idempotency_key.strip(),
        payload_fingerprint=fingerprint,
        case_for_access_check=locked_case,
    )
    if replayed_record is not None:
        return CommandExecutionResult(
            status_code=replayed_record.response_status,
            body=replayed_record.response_body,
            replayed=True,
        )

    # K2: Authenticate and check scope + delegated powers under lock
    scope = resolve_actor_scope(actor)
    if RoleCode.COMPETENT_AUTHORITY not in scope.roles:
        raise PermissionDenied("Only COMPETENT_AUTHORITY may record disposition decisions (Sheet 02 C1-C2).")
    if delegated_power_ref not in scope.delegated_powers:
        raise PermissionDenied(
            f"Actor lacks required delegated power '{delegated_power_ref}' (Sheet 02 C1)."
        )

    # K4: Compare expected version
    if locked_case.version != expected_version:
        raise StaleCaseVersionError(
            f"Stale case version: expected {expected_version}, actual {locked_case.version} (HTTP 409 — Sheet 06 K4)."
        )

    # K5: Validate transition under lock
    rule = validate_case_transition(
        case=locked_case,
        action=action,
        actor_roles=scope.roles,
    )
    if not locked_case.pinned_policy_version_id:
        raise TransitionViolationError("Case has no pinned policy version (Sheet 06 K5).")

    # Verify reviewed evidence versions belong to this case/institution and are CLEAN + ACCEPTED (Sheet 06 K5, Sheet 07 Q2)
    from apps.documents.models import DocumentVersion, QuarantineStatus, ReviewAcceptanceStatus

    ev_ids = reviewed_evidence_version_ids or []
    from apps.documents.services import validate_case_evidence
    validate_case_evidence(actor=actor, case=locked_case, evidence_ids=ev_ids, accepted=True)
    if ev_ids:
        valid_ev_count = DocumentVersion.objects.filter(
            id__in=ev_ids,
            institution_id=locked_case.institution_id,
            quarantine_status=QuarantineStatus.CLEAN,
            acceptance_status=ReviewAcceptanceStatus.ACCEPTED,
        ).count()
        if valid_ev_count != len(set(ev_ids)):
            raise TransitionViolationError(
                "All referenced evidence versions must be CLEAN and ACCEPTED for this institution (Sheet 06 K5, Sheet 07 Q2)."
            )

    requirements = (locked_case.pinned_policy_version.document_requirements or {}).get(locked_case.application_category, [])
    required_types = {item["document_type"] if isinstance(item, dict) else item for item in requirements}
    accepted_types = set(DocumentVersion.objects.filter(id__in=ev_ids, institution_id=locked_case.institution_id, quarantine_status=QuarantineStatus.CLEAN, acceptance_status=ReviewAcceptanceStatus.ACCEPTED).values_list("document_type", flat=True))
    if required_types - accepted_types:
        raise TransitionViolationError("Missing required reviewed document types: " + ", ".join(sorted(required_types - accepted_types)))

    old_version = locked_case.version
    new_version = old_version + 1
    now = timezone.now()

    # L1: Update domain state (decision + case state/version + refer-back stage or obligations/deadlines)
    is_final_disposition = outcome != DecisionOutcome.REFER_BACK
    try:
        decision = CaseDecision.objects.create(
            case=locked_case,
            outcome=outcome,
            decided_by=actor,
            decided_by_role=RoleCode.COMPETENT_AUTHORITY,
            delegated_power_ref=delegated_power_ref,
            pinned_policy_version=locked_case.pinned_policy_version,
            case_version_at_decision=new_version,
            reasons=reasons.strip(),
            reviewed_evidence_version_ids=ev_ids,
            refer_back_stage_type=refer_back_stage_type if not is_final_disposition else "",
            is_current_final=is_final_disposition,
        )
    except IntegrityError as exc:
        raise StaleCaseVersionError(
            "Concurrent final decision already recorded for this processing instance (Sheet 06 K6)."
        ) from exc

    locked_case.status = rule.destination_status
    locked_case.version = new_version

    if outcome == DecisionOutcome.REFER_BACK:
        if not refer_back_stage_type:
            raise ValidationError("REFER_BACK requires a target refer_back_stage_type (Sheet 02 C1).")
        locked_case.current_stage_type = refer_back_stage_type
        last_stage = (
            locked_case.stage_instances.filter(stage_type=refer_back_stage_type)
            .order_by("-iteration_number")
            .first()
        )
        next_iter = (last_stage.iteration_number + 1) if last_stage else 1
        next_seq = locked_case.stage_instances.count() + 1
        StageInstance.objects.create(
            case=locked_case,
            stage_type=refer_back_stage_type,
            sequence_number=next_seq,
            iteration_number=next_iter,
            status=StageStatus.PENDING,
        )
    else:
        locked_case.current_stage_type = ""

    locked_case.save(update_fields=["status", "current_stage_type", "version", "updated_at"])

    created_obligation_ids: list[str] = []
    for idx, ob_spec in enumerate(obligations_spec or [], start=1):
        due_days = int(ob_spec.get("due_days", 30))
        due_at = now + timedelta(days=due_days)
        dl = DeadlineRecord.objects.create(
            source_type="OBLIGATION",
            source_id=locked_case.id,
            case=locked_case,
            institution=locked_case.institution,
            region=locked_case.region,
            clock_type=ClockType.INSTITUTION_SUBMISSION,
            due_at=due_at,
            calendar_version=locked_case.pinned_policy_version.calendar_version,
            owner_role=ob_spec.get("verifier_role", RoleCode.REGIONAL_OFFICER),
            reminder_offsets_hours=ob_spec.get("reminder_offsets_hours", [168, 48, 0]),
            state=DeadlineState.ACTIVE,
        )
        ob = Obligation.objects.create(
            institution=locked_case.institution,
            case=locked_case,
            originating_decision=decision,
            source_command_ref=f"DECISION:{decision.id}:{idx}",
            obligation_code=ob_spec.get("obligation_code", f"OBLIG-{idx}"),
            condition_text=ob_spec["condition_text"],
            evidence_requirement=ob_spec.get("evidence_requirement", "Supporting document required"),
            verifier_role=ob_spec.get("verifier_role", RoleCode.REGIONAL_OFFICER),
            due_at=due_at,
            state=ObligationState.OPEN,
            active_deadline=dl,
        )
        dl.source_id = ob.id
        dl.save(update_fields=["source_id"])
        created_obligation_ids.append(str(ob.id))

    # L2: Append audit event and durable outbox event + save idempotency record
    corr_id = get_correlation_id()
    policy_ref = f"{locked_case.pinned_policy_version.policy_code}@v{locked_case.pinned_policy_version.version_number}"

    audit_event = record_audit_event(
        actor=actor,
        actor_role=RoleCode.COMPETENT_AUTHORITY,
        actor_scope=scope.to_audit_dict(),
        action=action,
        target_type="ApplicationCase",
        target_id=str(locked_case.id),
        case=locked_case,
        institution=locked_case.institution,
        region=locked_case.region,
        policy_version_ref=policy_ref,
        old_version=old_version,
        new_version=new_version,
        reason=reasons.strip(),
        inputs_snapshot=payload_for_hash,
        correlation_id=corr_id,
    )

    outbox_logical_id = f"decision:{decision.id}:v{new_version}"
    outbox_event = OutboxEvent.objects.create(
        logical_id=outbox_logical_id,
        event_type="DECISION_RECORDED",
        case=locked_case,
        case_version=new_version,
        payload={
            "decision_id": str(decision.id),
            "case_id": str(locked_case.id),
            "case_number": locked_case.case_number,
            "outcome": outcome,
            "case_version": new_version,
            "obligation_ids": created_obligation_ids,
        },
        state=OutboxState.PENDING,
        next_attempt_at=now,
        correlation_id=corr_id,
    )

    response_body = {
        "case_id": str(locked_case.id),
        "case_number": locked_case.case_number,
        "status": locked_case.status,
        "version": new_version,
        "decision_id": str(decision.id),
        "outcome": decision.outcome,
        "obligation_ids": created_obligation_ids,
        "audit_event_id": str(audit_event.id),
        "outbox_event_id": str(outbox_event.id),
        "delivery_state": "PENDING",
        "correlation_id": corr_id,
    }

    try:
        IdempotencyRecord.objects.create(
            actor=actor,
            action=action,
            idempotency_key=idempotency_key.strip(),
            case=locked_case,
            payload_fingerprint=fingerprint,
            response_status=200,
            response_body=response_body,
            correlation_id=corr_id,
        )
    except IntegrityError as exc:
        raise IdempotencyConflictError(
            f"Concurrent duplicate insertion for idempotency key '{idempotency_key}' (Sheet 06 K3)."
        ) from exc

    return CommandExecutionResult(status_code=200, body=response_body, replayed=False)


@transaction.atomic
def execute_guarded_stage_transition_command(
    *,
    actor: Any,
    case_id: Any,
    stage_instance_id: Any,
    action: str,
    expected_version: int,
    idempotency_key: str,
    reason: str,
    findings: list[dict[str, Any]] | None = None,
    recommendation: str = "",
) -> CommandExecutionResult:
    """Execute a guarded stage transition command (Sheet 02 B2-B3, Sheet 06 K1-K6, L1-L3)."""
    if not idempotency_key or not idempotency_key.strip():
        raise ValidationError("idempotency_key is required for stage transition commands.")
    if not reason or not reason.strip():
        raise ValidationError("Every stage mutation requires a recorded reason (Sheet 02 footer).")

    payload_for_hash = {
        "case_id": str(case_id),
        "stage_instance_id": str(stage_instance_id),
        "action": action,
        "expected_version": expected_version,
        "reason": reason.strip(),
        "findings": findings or [],
        "recommendation": recommendation,
    }
    fingerprint = compute_payload_fingerprint(payload_for_hash)

    locked_case = ApplicationCase.objects.select_for_update().get(pk=case_id)
    locked_stage = StageInstance.objects.select_for_update().get(pk=stage_instance_id, case=locked_case)

    replayed_record = _resolve_or_replay_command(
        actor=actor,
        action=action,
        idempotency_key=idempotency_key.strip(),
        payload_fingerprint=fingerprint,
        case_for_access_check=locked_case,
    )
    if replayed_record is not None:
        return CommandExecutionResult(
            status_code=replayed_record.response_status,
            body=replayed_record.response_body,
            replayed=True,
        )

    scope = check_stage_execution_access(actor, locked_case, locked_stage, action)

    if locked_case.version != expected_version:
        raise StaleCaseVersionError(
            f"Stale case version: expected {expected_version}, actual {locked_case.version} (HTTP 409 — Sheet 06 K4)."
        )

    if not isinstance(findings or [], list) or any(not isinstance(f, dict) for f in findings or []):
        raise ValidationError("Findings must be a list of structured observations.")
    from apps.documents.services import validate_case_evidence
    validate_case_evidence(actor=actor, case=locked_case, evidence_ids=[f["document_version_id"] for f in findings or [] if "document_version_id" in f])

    prescribed = list(locked_case.prescribed_stages or [])
    current_idx = prescribed.index(locked_stage.stage_type) if locked_stage.stage_type in prescribed else -1
    has_further_stage = current_idx >= 0 and (current_idx + 1) < len(prescribed)

    if action == "COMPLETE_STAGE":
        effective_action = "COMPLETE_STAGE_NEXT" if has_further_stage else "COMPLETE_FINAL_STAGE"
    else:
        effective_action = action

    if locked_stage.stage_type == StageType.EVC and effective_action in {"COMPLETE_STAGE_NEXT", "COMPLETE_FINAL_STAGE"}:
        from apps.evc.models import EvcCoordination, EvcStatus
        report = EvcCoordination.objects.filter(stage_instance=locked_stage, status=EvcStatus.REPORT_SUBMITTED).first()
        if report is None or not report.report_summary or not report.video_recording_ref or not report.observations:
            raise ValidationError("Complete the EVC evaluation report before advancing this stage.")

    rule = validate_case_transition(
        case=locked_case,
        action=effective_action,
        actor_roles=scope.roles,
        active_stage_type=locked_stage.stage_type,
    )

    old_version = locked_case.version
    new_version = old_version + 1
    now = timezone.now()

    if findings is not None:
        locked_stage.findings = findings
    if recommendation:
        locked_stage.recommendation = recommendation
    locked_stage.completion_reason = reason.strip()

    next_stage_id: str | None = None
    if effective_action == "RETURN_FOR_DEFICIENCY":
        from apps.cases.models import DeficiencyCycle

        locked_stage.status = StageStatus.RETURNED_FOR_DEFICIENCY
        locked_stage.save()
        DeficiencyCycle.objects.create(
            case=locked_case,
            stage_instance=locked_stage,
            deficiencies_recorded=findings or [],
            returned_by=actor,
            return_reason=reason.strip(),
        )
        locked_case.status = CaseStatus.DEFICIENCY_PENDING
    else:
        locked_stage.status = StageStatus.COMPLETED
        locked_stage.completed_at = now
        locked_stage.completed_by = actor
        locked_stage.save()

        if has_further_stage:
            next_stage_type = prescribed[current_idx + 1]
            next_stage = StageInstance.objects.create(
                case=locked_case,
                stage_type=next_stage_type,
                sequence_number=locked_stage.sequence_number + 1,
                iteration_number=1,
                status=StageStatus.PENDING,
            )
            from apps.policy.runtime import create_stage_deadline
            create_stage_deadline(locked_case, next_stage, now)
            next_stage_id = str(next_stage.id)
            locked_case.status = CaseStatus.IN_STAGE_PROCESSING
            locked_case.current_stage_type = next_stage_type
        else:
            locked_case.status = rule.destination_status
            locked_case.current_stage_type = ""

    locked_case.version = new_version
    locked_case.save(update_fields=["status", "current_stage_type", "version", "updated_at"])

    corr_id = get_correlation_id()
    policy_ref = (
        f"{locked_case.pinned_policy_version.policy_code}@v{locked_case.pinned_policy_version.version_number}"
        if locked_case.pinned_policy_version
        else ""
    )

    audit_event = record_audit_event(
        actor=actor,
        actor_role=",".join(sorted(scope.roles)),
        actor_scope=scope.to_audit_dict(),
        action=effective_action,
        target_type="StageInstance",
        target_id=str(locked_stage.id),
        case=locked_case,
        institution=locked_case.institution,
        region=locked_case.region,
        policy_version_ref=policy_ref,
        old_version=old_version,
        new_version=new_version,
        reason=reason.strip(),
        inputs_snapshot=payload_for_hash,
        correlation_id=corr_id,
    )

    outbox_event = OutboxEvent.objects.create(
        logical_id=f"stage:{locked_stage.id}:v{new_version}",
        event_type=f"STAGE_{effective_action}",
        case=locked_case,
        case_version=new_version,
        payload={
            "case_id": str(locked_case.id),
            "stage_instance_id": str(locked_stage.id),
            "stage_type": locked_stage.stage_type,
            "action": effective_action,
            "next_stage_id": next_stage_id,
            "case_version": new_version,
        },
        state=OutboxState.PENDING,
        next_attempt_at=now,
        correlation_id=corr_id,
    )

    response_body = {
        "case_id": str(locked_case.id),
        "stage_instance_id": str(locked_stage.id),
        "stage_status": locked_stage.status,
        "case_status": locked_case.status,
        "current_stage_type": locked_case.current_stage_type,
        "next_stage_id": next_stage_id,
        "version": new_version,
        "audit_event_id": str(audit_event.id),
        "outbox_event_id": str(outbox_event.id),
        "correlation_id": corr_id,
    }

    IdempotencyRecord.objects.create(
        actor=actor,
        action=action,
        idempotency_key=idempotency_key.strip(),
        case=locked_case,
        payload_fingerprint=fingerprint,
        response_status=200,
        response_body=response_body,
        correlation_id=corr_id,
    )

    return CommandExecutionResult(status_code=200, body=response_body, replayed=False)
