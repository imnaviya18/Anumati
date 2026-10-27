"""EVC coordination services: readiness check, atomic slot reservation, human confirmation, rescheduling with reason, evaluation conduct, and report completion (Sheet 01 Block 03, Sheet 04 G1-G5, PS Section C, APH 1.9)."""
from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.access.models import CaseAssignment, RoleCode
from apps.access.services import check_case_read_access, create_case_assignment, resolve_actor_scope
from apps.audit.services import record_audit_event
from apps.cases.models import ApplicationCase, StageInstance, StageStatus, StageType
from apps.deadlines.models import ClockType, DeadlineRecord, DeadlineState
from apps.decisions.services import execute_guarded_stage_transition_command
from apps.evc.models import EvcCoordination, EvcMode, EvcSlot, EvcStatus
from apps.organisation.models import Committee
from apps.outbox.models import OutboxEvent, OutboxState


@transaction.atomic
def check_evc_readiness_and_queue(
    *,
    actor: Any,
    case_id: Any,
    stage_instance_id: Any,
    mode: str = EvcMode.ONLINE,
    reason: str = "Preliminary stages complete; EVC readiness verified (Sheet 04 G1)",
) -> EvcCoordination:
    """Sheet 04 G1 & PS Section C: Verify required preceding stages are complete and case is in EVC stage; mark READY and set distinct scheduling/completion timelines for new vs existing institutions."""
    scope = resolve_actor_scope(actor)
    allowed = {RoleCode.REGIONAL_OFFICER, RoleCode.BUREAU_OFFICER, RoleCode.EVC_MEMBER}
    if not (scope.roles & allowed):
        raise PermissionDenied("Actor is not authorised to verify EVC readiness (Sheet 04 G1).")

    locked_case = ApplicationCase.objects.select_for_update(of=("self",)).select_related("institution", "pinned_policy_version").get(
        pk=case_id
    )
    check_case_read_access(actor, locked_case)
    stage = StageInstance.objects.select_for_update().get(pk=stage_instance_id, case=locked_case)
    if stage.stage_type != StageType.EVC:
        raise ValidationError("Stage instance is not an EVC stage (Sheet 04 G1).")

    # Verify all preceding prescribed stages before EVC are COMPLETED (Sheet 04 G1)
    prescribed = list(locked_case.prescribed_stages or [])
    if StageType.EVC not in prescribed:
        raise ValidationError("Case route does not prescribe an EVC stage (Sheet 04 G1).")
    evc_index = prescribed.index(StageType.EVC)
    preceding_types = prescribed[:evc_index]
    completed_types = set(
        locked_case.stage_instances.filter(status=StageStatus.COMPLETED).values_list("stage_type", flat=True)
    )
    for pre in preceding_types:
        if pre not in completed_types:
            raise ValidationError(
                f"Preceding stage '{pre}' is not complete; EVC readiness check failed (Sheet 04 G1)."
            )

    from apps.policy.runtime import due_after_days
    now = timezone.now()
    is_new_inst = bool(locked_case.institution.is_new_institution)
    evc_rules = (locked_case.pinned_policy_version.evc_rules if locked_case.pinned_policy_version else {}) or {}

    # Distinct rule type for new institutions vs existing institutions (PS Section C)
    rule_bucket = evc_rules.get("new_institution" if is_new_inst else "existing_institution", {})
    sched_days = int(rule_bucket.get("scheduling_sla_days", 7 if is_new_inst else 14))
    comp_days = int(rule_bucket.get("completion_sla_days", 15 if is_new_inst else 30))
    cal_ver = locked_case.pinned_policy_version.calendar_version if locked_case.pinned_policy_version else "CAL-v1"

    sched_dl = DeadlineRecord.objects.create(
        source_type="EVC_SCHEDULING",
        source_id=stage.id,
        case=locked_case,
        institution=locked_case.institution,
        region=locked_case.region,
        clock_type=ClockType.EVC_SCHEDULING,
        due_at=due_after_days(now, sched_days, locked_case.pinned_policy_version, "EVC_SCHEDULING"),
        calendar_version=cal_ver,
        owner_role=RoleCode.REGIONAL_OFFICER,
        reminder_offsets_hours=[48, 24, 0],
        state=DeadlineState.ACTIVE,
    )
    comp_dl = DeadlineRecord.objects.create(
        source_type="EVC_COMPLETION",
        source_id=stage.id,
        case=locked_case,
        institution=locked_case.institution,
        region=locked_case.region,
        clock_type=ClockType.EVC_COMPLETION,
        due_at=due_after_days(now, comp_days, locked_case.pinned_policy_version, "EVC_COMPLETION"),
        calendar_version=cal_ver,
        owner_role=RoleCode.REGIONAL_OFFICER,
        reminder_offsets_hours=[72, 24, 0],
        state=DeadlineState.ACTIVE,
    )

    coord, _ = EvcCoordination.objects.update_or_create(
        case=locked_case,
        stage_instance=stage,
        defaults={
            "is_new_institution_rule": is_new_inst,
            "mode": mode,
            "status": EvcStatus.READY,
            "readiness_checked_by": actor,
            "readiness_checked_at": now,
            "scheduling_deadline": sched_dl,
            "completion_deadline": comp_dl,
        },
    )

    record_audit_event(
        actor=actor,
        actor_role=",".join(sorted(scope.roles)),
        actor_scope=scope.to_audit_dict(),
        action="EVC_READINESS_VERIFIED",
        target_type="EvcCoordination",
        target_id=str(coord.id),
        case=locked_case,
        reason=reason,
        inputs_snapshot={
            "is_new_institution_rule": is_new_inst,
            "mode": mode,
            "scheduling_sla_days": sched_days,
            "completion_sla_days": comp_days,
        },
    )
    return coord


@transaction.atomic
def reserve_evc_slot_atomically(
    *,
    actor: Any,
    coordination_id: Any,
    committee_id: Any,
    slot_start: timezone.datetime,
    slot_end: timezone.datetime,
    reason: str = "Reserve EVC slot (Sheet 04 G2)",
) -> EvcSlot:
    """Sheet 04 G2 & Sheet 07 N4: Check authorised eligibility/conflicts and reserve slot atomically against concurrent bookings."""
    scope = resolve_actor_scope(actor)
    if not (scope.roles & {RoleCode.REGIONAL_OFFICER, RoleCode.BUREAU_OFFICER}):
        raise PermissionDenied("Only Regional or Bureau Officers may reserve EVC committee slots (Sheet 04 G2).")
    if slot_end <= slot_start:
        raise ValidationError("slot_end must be after slot_start.")

    coord = EvcCoordination.objects.select_for_update(of=("self",)).select_related("case").get(pk=coordination_id)
    check_case_read_access(actor, coord.case)
    if coord.status not in {EvcStatus.READY, EvcStatus.RESCHEDULE_REQUIRED}:
        raise ValidationError(f"EVC coordination must be READY or RESCHEDULE_REQUIRED to reserve a slot (got '{coord.status}').")

    committee = Committee.objects.select_for_update().get(pk=committee_id)
    if committee.committee_type != Committee.CommitteeType.EVC or not committee.is_currently_valid():
        raise ValidationError("Selected committee is not an active valid EVC committee (Sheet 04 G2).")

    # Check overlapping reserved slots for the same committee
    overlapping = EvcSlot.objects.select_for_update().filter(
        committee=committee,
        is_reserved=True,
        slot_start__lt=slot_end,
        slot_end__gt=slot_start,
    )
    if overlapping.exists():
        raise ValidationError("Concurrent or overlapping EVC slot booking conflict for this committee (Sheet 04 G2).")

    # Release any previously held slot by this coordination
    EvcSlot.objects.filter(reserved_by_coordination=coord).update(
        is_reserved=False,
        reserved_by_coordination=None,
    )

    try:
        slot, created = EvcSlot.objects.select_for_update().get_or_create(
            committee=committee,
            slot_start=slot_start,
            defaults={
                "slot_end": slot_end,
                "mode": coord.mode,
                "is_reserved": True,
                "reserved_by_coordination": coord,
            },
        )
        if not created:
            if slot.is_reserved:
                raise ValidationError("EVC slot is already reserved by another booking (Sheet 04 G2).")
            slot.slot_end = slot_end
            slot.mode = coord.mode
            slot.is_reserved = True
            slot.reserved_by_coordination = coord
            slot.save()
    except IntegrityError as exc:
        raise ValidationError("Concurrent EVC slot reservation conflict detected (Sheet 04 G2).") from exc

    coord.committee = committee
    coord.scheduled_start = slot_start
    coord.scheduled_end = slot_end
    coord.status = EvcStatus.SLOT_RESERVED
    coord.save(update_fields=["committee", "scheduled_start", "scheduled_end", "status", "updated_at"])

    record_audit_event(
        actor=actor,
        actor_role=",".join(sorted(scope.roles)),
        actor_scope=scope.to_audit_dict(),
        action="EVC_SLOT_RESERVED",
        target_type="EvcCoordination",
        target_id=str(coord.id),
        case=coord.case,
        reason=reason,
        inputs_snapshot={
            "committee_id": str(committee.id),
            "slot_start": slot_start.isoformat(),
            "slot_end": slot_end.isoformat(),
        },
    )
    return slot


@transaction.atomic
def confirm_or_reject_evc_schedule(
    *,
    actor: Any,
    coordination_id: Any,
    confirmed: bool,
    reason: str,
) -> EvcCoordination:
    """Sheet 04 G2-G3: Human confirmation of reserved EVC schedule.

    - If confirmed: status -> SCHEDULE_CONFIRMED, assign committee to stage, complete scheduling deadline, queue visit notification.
    - If not confirmed: record blocker, release slot, status -> RESCHEDULE_REQUIRED (due checks continue via H1).
    """
    scope = resolve_actor_scope(actor)
    if not (scope.roles & {RoleCode.REGIONAL_OFFICER, RoleCode.BUREAU_OFFICER, RoleCode.EVC_MEMBER, RoleCode.COMPETENT_AUTHORITY}):
        raise PermissionDenied("Actor is not authorised to confirm EVC schedule (Sheet 04 G2).")
    if not reason or not reason.strip():
        raise ValidationError("Schedule confirmation or blocker rejection requires a recorded reason.")

    coord = EvcCoordination.objects.select_for_update(of=("self",)).select_related("case", "stage_instance", "committee").get(
        pk=coordination_id
    )
    check_case_read_access(actor, coord.case)
    if coord.status != EvcStatus.SLOT_RESERVED:
        raise ValidationError("EVC schedule must be in SLOT_RESERVED state before human confirmation (Sheet 04 G2).")

    now = timezone.now()
    if not confirmed:
        EvcSlot.objects.filter(reserved_by_coordination=coord).update(
            is_reserved=False,
            reserved_by_coordination=None,
        )
        coord.status = EvcStatus.RESCHEDULE_REQUIRED
        coord.blocker_reason = reason.strip()
        coord.save(update_fields=["status", "blocker_reason", "updated_at"])
        record_audit_event(
            actor=actor,
            actor_role=",".join(sorted(scope.roles)),
            actor_scope=scope.to_audit_dict(),
            action="EVC_SCHEDULE_BLOCKED",
            target_type="EvcCoordination",
            target_id=str(coord.id),
            case=coord.case,
            reason=reason.strip(),
        )
        return coord

    coord.status = EvcStatus.SCHEDULE_CONFIRMED
    coord.confirmed_by = actor
    coord.confirmed_at = now
    coord.blocker_reason = ""
    coord.save(update_fields=["status", "confirmed_by", "confirmed_at", "blocker_reason", "updated_at"])

    if coord.scheduling_deadline_id:
        DeadlineRecord.objects.filter(pk=coord.scheduling_deadline_id).update(state=DeadlineState.COMPLETED)

    create_case_assignment(
        actor=actor,
        case=coord.case,
        stage_instance=coord.stage_instance,
        target_committee=coord.committee,
        assignment_scope=CaseAssignment.AssignmentScope.EVC_EVALUATOR,
        reason=f"Confirmed EVC schedule for committee {coord.committee.code}",
    )

    sched_revision = len(coord.schedule_history or []) + 1
    OutboxEvent.objects.create(
        logical_id=f"evc-scheduled:{coord.id}:rev{sched_revision}:{now.strftime('%Y%m%d%H%M%S%f')}",
        event_type="EVC_VISIT_SCHEDULED",
        case=coord.case,
        payload={
            "coordination_id": str(coord.id),
            "schedule_revision": sched_revision,
            "scheduled_start": coord.scheduled_start.isoformat() if coord.scheduled_start else "",
        },
        state=OutboxState.PENDING,
        next_attempt_at=now,
    )

    record_audit_event(
        actor=actor,
        actor_role=",".join(sorted(scope.roles)),
        actor_scope=scope.to_audit_dict(),
        action="EVC_SCHEDULE_CONFIRMED",
        target_type="EvcCoordination",
        target_id=str(coord.id),
        case=coord.case,
        reason=reason.strip(),
    )
    return coord


@transaction.atomic
def reschedule_evc_visit(
    *,
    actor: Any,
    coordination_id: Any,
    reason: str,
    is_no_show: bool = False,
) -> EvcCoordination:
    """Sheet 04 G3 & G4: Rescheduling / cancellation / no-show requires recorded reason and retains old schedule in history."""
    scope = resolve_actor_scope(actor)
    if not (scope.roles & {RoleCode.REGIONAL_OFFICER, RoleCode.BUREAU_OFFICER, RoleCode.EVC_MEMBER}):
        raise PermissionDenied("Actor is not authorised to reschedule EVC visit.")
    if not reason or not reason.strip():
        raise ValidationError("Rescheduling requires an explicit recorded reason (Sheet 04 G3).")

    coord = EvcCoordination.objects.select_for_update(of=("self",)).select_related("case").get(pk=coordination_id)
    check_case_read_access(actor, coord.case)
    history = list(coord.schedule_history or [])
    history.append(
        {
            "previous_committee_id": str(coord.committee_id) if coord.committee_id else None,
            "previous_start": coord.scheduled_start.isoformat() if coord.scheduled_start else None,
            "previous_end": coord.scheduled_end.isoformat() if coord.scheduled_end else None,
            "rescheduled_at": timezone.now().isoformat(),
            "rescheduled_by": actor.pk,
            "is_no_show": is_no_show,
            "reason": reason.strip(),
        }
    )

    EvcSlot.objects.filter(reserved_by_coordination=coord).update(
        is_reserved=False,
        reserved_by_coordination=None,
    )

    coord.schedule_history = history
    coord.status = EvcStatus.RESCHEDULE_REQUIRED
    coord.blocker_reason = reason.strip()
    coord.save(update_fields=["schedule_history", "status", "blocker_reason", "updated_at"])

    record_audit_event(
        actor=actor,
        actor_role=",".join(sorted(scope.roles)),
        actor_scope=scope.to_audit_dict(),
        action="EVC_VISIT_NO_SHOW_RESCHEDULE" if is_no_show else "EVC_VISIT_RESCHEDULED",
        target_type="EvcCoordination",
        target_id=str(coord.id),
        case=coord.case,
        reason=reason.strip(),
        inputs_snapshot=history[-1],
    )
    return coord


@transaction.atomic
def conduct_and_complete_evc_report(
    *,
    actor: Any,
    coordination_id: Any,
    expected_case_version: int,
    idempotency_key: str,
    observations: dict[str, Any],
    evidence_version_ids: list[str],
    video_recording_ref: str,
    gps_coordinates: str,
    report_summary: str,
    recommendation: str,
) -> dict[str, Any]:
    """Sheet 04 G4-G5 & APH 1.9: Record evaluation observations, verify required completion records are present, complete EVC stage -> B3 (findings are not the final approval decision)."""
    from apps.decisions.services import compute_payload_fingerprint, _resolve_or_replay_command
    from apps.decisions.models import IdempotencyRecord
    if not idempotency_key.strip():
        raise ValidationError("A report idempotency key is required.")
    identity = EvcCoordination.objects.get(pk=coordination_id)
    case = ApplicationCase.objects.select_for_update().get(pk=identity.case_id)
    check_case_read_access(actor, case)
    fingerprint = compute_payload_fingerprint({"coordination_id":str(coordination_id), "version":expected_case_version,
        "observations":observations, "evidence":evidence_version_ids, "video":video_recording_ref,
        "gps":gps_coordinates, "summary":report_summary, "recommendation":recommendation})
    replay = _resolve_or_replay_command(actor=actor,action="EVC_REPORT",idempotency_key=idempotency_key,
        payload_fingerprint=fingerprint,case_for_access_check=case)
    if replay:
        return replay.response_body
    coord = EvcCoordination.objects.select_for_update(of=("self",)).select_related("case", "stage_instance").get(pk=coordination_id)
    if coord.status not in {EvcStatus.SCHEDULE_CONFIRMED, EvcStatus.VISIT_CONDUCTED}:
        raise ValidationError(f"EVC visit cannot be conducted in state '{coord.status}' (Sheet 04 G4).")

    from apps.documents.services import validate_case_evidence
    validate_case_evidence(actor=actor, case=case, evidence_ids=evidence_version_ids)

    # Sheet 04 G4 diamond: "Required completion records present? NO -> Request missing report/records; return G4"
    missing_fields: list[str] = []
    if not observations:
        missing_fields.append("observations")
    if not video_recording_ref or not video_recording_ref.strip():
        missing_fields.append("video_recording_ref (APH 1.9f/g)")
    if coord.mode == EvcMode.PHYSICAL and (not gps_coordinates or not gps_coordinates.strip()):
        missing_fields.append("gps_coordinates (APH 1.9g Note)")
    if not report_summary or not report_summary.strip():
        missing_fields.append("report_summary")

    if missing_fields:
        coord.status = EvcStatus.VISIT_CONDUCTED
        coord.observations = observations or {}
        coord.save(update_fields=["status", "observations", "updated_at"])
        raise ValidationError(
            f"Incomplete EVC completion records: {', '.join(missing_fields)} required before completing EVC stage (Sheet 04 G4)."
        )

    now = timezone.now()
    coord.observations = observations
    coord.evidence_version_ids = evidence_version_ids
    coord.video_recording_ref = video_recording_ref.strip()
    coord.gps_coordinates = gps_coordinates.strip()
    coord.report_summary = report_summary.strip()
    coord.report_submitted_by = actor
    coord.report_submitted_at = now
    coord.status = EvcStatus.REPORT_SUBMITTED
    coord.save()

    if coord.completion_deadline_id:
        DeadlineRecord.objects.filter(pk=coord.completion_deadline_id).update(state=DeadlineState.COMPLETED)

    # G5 -> B3: Run guarded stage completion command; findings are not the final approval decision
    stage_res = execute_guarded_stage_transition_command(
        actor=actor,
        case_id=coord.case_id,
        stage_instance_id=coord.stage_instance_id,
        action="COMPLETE_STAGE",
        expected_version=expected_case_version,
        idempotency_key=idempotency_key,
        reason=report_summary.strip(),
        findings=[{"evc_observations": observations, "video_ref": video_recording_ref.strip()}],
        recommendation=recommendation,
    )
    response = {
        "coordination_id": str(coord.id),
        "evc_status": coord.status,
        "stage_transition": stage_res.body,
    }

    IdempotencyRecord.objects.create(actor=actor,action="EVC_REPORT",idempotency_key=idempotency_key,
        case=case,payload_fingerprint=fingerprint,response_status=200,response_body=response)
    return response
