"""Case lifecycle services: intake, route resolution, scrutiny/re-scrutiny, deficiency response, closure, and appeal/reopening (Sheet 02 A1-A4, B1-B4, C4, PS Section A)."""
from __future__ import annotations

from typing import Any
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.access.models import RoleCode
from apps.access.services import check_case_read_access, resolve_actor_scope
from apps.audit.services import record_audit_event
from apps.cases.models import (
    ApplicationCase,
    CaseStatus,
    DeficiencyCycle,
    StageInstance,
    StageStatus,
    StageType,
)
from apps.evc.models import EvcCoordination, EvcMode, EvcStatus
from apps.policy.models import PolicyVersion
from apps.routing.services import (
    TransitionViolationError,
    evaluate_policy_route,
    validate_case_transition,
)


@transaction.atomic
def submit_or_import_application(
    *,
    actor: Any,
    institution: Any,
    academic_cycle: str,
    application_category: str,
    source_id: str,
    programme_level: str = "UNDER_GRADUATE",
    requested_courses: list[dict[str, Any]] | None = None,
    input_snapshot: dict[str, Any] | None = None,
    responsible_bureau: Any = None,
    save_as_draft_only: bool = False,
) -> ApplicationCase:
    """Sheet 02 A1-A4: Submit or import an application, validate intake, resolve applicable effective policy, pin rule version, and create first stage + deadline."""
    scope = resolve_actor_scope(actor)
    allowed_roles = {RoleCode.INSTITUTION_USER, RoleCode.BUREAU_OFFICER, RoleCode.REGIONAL_OFFICER}
    if not (scope.roles & allowed_roles):
        raise PermissionDenied("Actor is not authorised to submit or import an application (Sheet 02 A1).")
    if RoleCode.INSTITUTION_USER in scope.roles and institution.id not in scope.institution_ids:
        raise PermissionDenied("Institution user cannot submit an application for another institution (Sheet 07 Q2).")

    if RoleCode.REGIONAL_OFFICER in scope.roles and RoleCode.INSTITUTION_USER not in scope.roles:
        if institution.region_id not in scope.region_ids:
            raise PermissionDenied("Cannot import applications outside assigned region.")
    if RoleCode.BUREAU_OFFICER in scope.roles and RoleCode.INSTITUTION_USER not in scope.roles:
        if responsible_bureau is None or responsible_bureau.id not in scope.bureau_ids:
            raise PermissionDenied("An assigned responsible bureau is required for bureau intake.")

    if not source_id or not source_id.strip():
        raise ValidationError("source_id is required for application intake (Sheet 02 A1).")
    if not academic_cycle or not academic_cycle.strip():
        raise ValidationError("academic_cycle is required for application intake (Sheet 02 A1).")
    if not application_category or not application_category.strip():
        raise ValidationError("application_category is required for application intake (Sheet 02 A1).")

    now = timezone.now()
    case_number = f"AICTE-{academic_cycle}-{uuid.uuid4().hex[:8].upper()}"

    case = ApplicationCase.objects.create(
        case_number=case_number,
        source_id=source_id.strip(),
        institution=institution,
        region=institution.region,
        responsible_bureau=responsible_bureau,
        academic_cycle=academic_cycle.strip(),
        application_category=application_category.strip(),
        programme_level=programme_level,
        requested_courses=requested_courses or [],
        input_snapshot=input_snapshot or {},
        status=CaseStatus.DRAFT,
        version=1,
    )

    record_audit_event(
        actor=actor,
        actor_role=",".join(sorted(scope.roles)),
        actor_scope=scope.to_audit_dict(),
        action="APPLICATION_INTAKE_CREATED",
        target_type="ApplicationCase",
        target_id=str(case.id),
        case=case,
        institution=institution,
        region=institution.region,
        old_version=0,
        new_version=1,
        reason="Application intake created (Sheet 02 A1)",
        inputs_snapshot={
            "source_id": case.source_id,
            "application_category": case.application_category,
            "academic_cycle": case.academic_cycle,
        },
    )

    if save_as_draft_only:
        return case

    # Transition DRAFT -> SUBMITTED (A1 pass)
    validate_case_transition(case=case, action="SUBMIT_APPLICATION", actor_roles=scope.roles)
    case.status = CaseStatus.SUBMITTED
    case.submitted_at = now
    case.version += 1
    case.save(update_fields=["status", "submitted_at", "version", "updated_at"])

    # A2: Resolve applicable policy and route
    return resolve_and_dispatch_case_route(actor=actor, case=case, reason="Initial intake route resolution (A2)")


@transaction.atomic
def resolve_and_dispatch_case_route(
    *,
    actor: Any,
    case: ApplicationCase,
    reason: str = "Resolve applicable policy route",
    explicit_policy: PolicyVersion | None = None,
) -> ApplicationCase:
    """Sheet 02 A2-A4: Find approved effective policy version, evaluate route conditions, pin rule version, and create first stage + deadline.

    If zero or multiple routes match, moves to POLICY_REVIEW_REQUIRED (never defaults to approval — Sheet 02 A2).
    """
    scope = resolve_actor_scope(actor)
    locked_case = ApplicationCase.objects.select_for_update().get(pk=case.pk)
    check_case_read_access(actor, locked_case)
    if not reason.strip():
        raise ValidationError("A route resolution reason is required.")
    now = timezone.now()
    if explicit_policy is not None:
        if not (scope.roles & {RoleCode.POLICY_ADMIN, RoleCode.COMPETENT_AUTHORITY, RoleCode.BUREAU_OFFICER}):
            raise PermissionDenied("Explicit policy selection requires policy authority.")
        if (explicit_policy.state != PolicyVersion.PolicyState.ACTIVE
                or explicit_policy.academic_cycle != locked_case.academic_cycle
                or explicit_policy.effective_from > now
                or (explicit_policy.effective_until and explicit_policy.effective_until <= now)):
            raise ValidationError("Policy must be active, effective and match the academic cycle.")

    policy = explicit_policy
    if policy is None:
        policy = (
            PolicyVersion.objects.filter(
                academic_cycle=locked_case.academic_cycle,
                state=PolicyVersion.PolicyState.ACTIVE,
                effective_from__lte=now,
            )
            .filter(models_q_effective_until(now))
            .order_by("-version_number")
            .first()
        )

    old_ver = locked_case.version
    new_ver = old_ver + 1

    if policy is None:
        validate_case_transition(case=locked_case, action="RESOLVE_ROUTE_AMBIGUOUS", actor_roles=scope.roles)
        locked_case.status = CaseStatus.POLICY_REVIEW_REQUIRED
        locked_case.route_explanation = {"error": "No active effective PolicyVersion found for academic cycle."}
        locked_case.version = new_ver
        locked_case.save(update_fields=["status", "route_explanation", "version", "updated_at"])
        record_audit_event(
            actor=actor,
            actor_role=",".join(sorted(scope.roles)),
            actor_scope=scope.to_audit_dict(),
            action="RESOLVE_ROUTE_NO_ACTIVE_POLICY",
            target_type="ApplicationCase",
            target_id=str(locked_case.id),
            case=locked_case,
            old_version=old_ver,
            new_version=new_ver,
            reason=reason,
        )
        return locked_case

    eval_result = evaluate_policy_route(
        policy=policy,
        application_category=locked_case.application_category,
        institution_category=locked_case.institution.category,
        is_new_institution=locked_case.institution.is_new_institution,
        extra_attributes=locked_case.input_snapshot,
    )

    locked_case.pinned_policy_version = policy
    locked_case.route_explanation = eval_result

    if eval_result["matched_count"] != 1 or not eval_result["selected_route"]:
        validate_case_transition(case=locked_case, action="RESOLVE_ROUTE_AMBIGUOUS", actor_roles=scope.roles)
        locked_case.status = CaseStatus.POLICY_REVIEW_REQUIRED
        locked_case.version = new_ver
        locked_case.save(
            update_fields=["pinned_policy_version", "route_explanation", "status", "version", "updated_at"]
        )
        record_audit_event(
            actor=actor,
            actor_role=",".join(sorted(scope.roles)),
            actor_scope=scope.to_audit_dict(),
            action="RESOLVE_ROUTE_AMBIGUOUS",
            target_type="ApplicationCase",
            target_id=str(locked_case.id),
            case=locked_case,
            policy_version_ref=f"{policy.policy_code}@v{policy.version_number}",
            old_version=old_ver,
            new_version=new_ver,
            reason=f"Matched {eval_result['matched_count']} routes; policy review required (Sheet 02 A2).",
            inputs_snapshot=eval_result,
        )
        return locked_case

    # A3 & A4: Exactly one valid route selected -> pin rule version, create first stage + deadline, dispatch
    validate_case_transition(case=locked_case, action="RESOLVE_ROUTE_SUCCESS", actor_roles=scope.roles)
    selected_route = eval_result["selected_route"]
    stages: list[str] = list(selected_route.get("stages") or [])
    if not stages:
        raise ValidationError("Selected policy route must prescribe at least one verification stage (Sheet 02 A2).")

    first_stage_type = stages[0]
    locked_case.selected_route_code = selected_route.get("route_code", "CUSTOM_ROUTE")
    locked_case.prescribed_stages = stages
    locked_case.status = CaseStatus.IN_STAGE_PROCESSING
    locked_case.current_stage_type = first_stage_type
    locked_case.version = new_ver
    locked_case.save(
        update_fields=[
            "pinned_policy_version",
            "selected_route_code",
            "prescribed_stages",
            "route_explanation",
            "status",
            "current_stage_type",
            "version",
            "updated_at",
        ]
    )

    first_stage = StageInstance.objects.create(
        case=locked_case,
        stage_type=first_stage_type,
        sequence_number=1,
        iteration_number=1,
        status=StageStatus.IN_PROGRESS,
        started_at=now,
    )

    from apps.policy.runtime import create_stage_deadline
    create_stage_deadline(locked_case, first_stage, now)

    if first_stage_type == StageType.EVC:
        EvcCoordination.objects.get_or_create(
            case=locked_case,
            stage_instance=first_stage,
            defaults={
                "is_new_institution_rule": locked_case.institution.is_new_institution,
                "mode": EvcMode.ONLINE,
                "status": EvcStatus.QUEUED,
            },
        )

    record_audit_event(
        actor=actor,
        actor_role=",".join(sorted(scope.roles)),
        actor_scope=scope.to_audit_dict(),
        action="CASE_ROUTE_PINNED_AND_DISPATCHED",
        target_type="ApplicationCase",
        target_id=str(locked_case.id),
        case=locked_case,
        policy_version_ref=f"{policy.policy_code}@v{policy.version_number}",
        old_version=old_ver,
        new_version=new_ver,
        reason=reason,
        inputs_snapshot={
            "selected_route_code": locked_case.selected_route_code,
            "prescribed_stages": stages,
            "first_stage_id": str(first_stage.id),
        },
    )
    return locked_case


def models_q_effective_until(now: timezone.datetime):
    from django.db.models import Q

    return Q(effective_until__isnull=True) | Q(effective_until__gte=now)


@transaction.atomic
def submit_deficiency_response(
    *,
    actor: Any,
    case_id: Any,
    expected_version: int,
    response_text: str,
    response_evidence_ids: list[str] | None = None,
) -> StageInstance:
    """Sheet 02 B2: Institution responds to recorded deficiencies -> creates re-review stage iteration preserving history and returns to B1."""
    scope = resolve_actor_scope(actor)
    locked_case = ApplicationCase.objects.select_for_update().get(pk=case_id)
    check_case_read_access(actor, locked_case)

    if RoleCode.INSTITUTION_USER not in scope.roles or locked_case.institution_id not in scope.institution_ids:
        raise PermissionDenied("Only the applicant institution's user may submit a deficiency response (Sheet 02 B2).")
    if locked_case.version != expected_version:
        from apps.decisions.services import StaleCaseVersionError

        raise StaleCaseVersionError(f"Stale case version: expected {expected_version}, actual {locked_case.version}.")

    validate_case_transition(
        case=locked_case,
        action="SUBMIT_DEFICIENCY_RESPONSE",
        actor_roles=scope.roles,
        active_stage_type=locked_case.current_stage_type,
    )

    open_cycle = (
        DeficiencyCycle.objects.select_for_update()
        .filter(case=locked_case, is_resolved=False)
        .order_by("-returned_at")
        .first()
    )
    if open_cycle is None:
        raise ValidationError("No open deficiency cycle found for this case.")

    if not response_text.strip():
        raise ValidationError("A deficiency response is required.")
    from apps.access.selectors import scope_documents_queryset
    evidence_ids = set(str(value) for value in response_evidence_ids or [])
    available_ids = set(str(value) for value in scope_documents_queryset(actor).filter(institution=locked_case.institution, id__in=evidence_ids).exclude(quarantine_status="REJECTED").values_list("id", flat=True))
    if evidence_ids != available_ids:
        raise PermissionDenied("Response evidence must belong to the institution and be available in scope.")
    now = timezone.now()
    open_cycle.institution_response = response_text.strip()
    open_cycle.response_evidence_ids = response_evidence_ids or []
    open_cycle.responded_by = actor
    open_cycle.responded_at = now
    open_cycle.is_resolved = True
    open_cycle.save()

    prev_stage = open_cycle.stage_instance
    # APH 1.8(f)-(g): Scrutiny deficiency response enters RE_SCRUTINY or next iteration of same stage preserving previous StageInstance
    next_stage_type = (
        StageType.RE_SCRUTINY
        if prev_stage.stage_type == StageType.SCRUTINY
        else prev_stage.stage_type
    )
    last_of_type = (
        locked_case.stage_instances.filter(stage_type=next_stage_type)
        .order_by("-iteration_number")
        .first()
    )
    next_iter = (last_of_type.iteration_number + 1) if last_of_type else 1

    # Ensure prescribed_stages includes RE_SCRUTINY if transitioned from SCRUTINY
    prescribed = list(locked_case.prescribed_stages or [])
    if next_stage_type == StageType.RE_SCRUTINY and StageType.RE_SCRUTINY not in prescribed:
        scr_idx = prescribed.index(StageType.SCRUTINY) if StageType.SCRUTINY in prescribed else 0
        prescribed.insert(scr_idx + 1, StageType.RE_SCRUTINY)
        # Mark original SCRUTINY iteration completed by deficiency cycle handover so route progression tracks RE_SCRUTINY
        prev_stage.status = StageStatus.COMPLETED
        prev_stage.completed_at = now
        prev_stage.save(update_fields=["status", "completed_at", "updated_at"])

    new_stage = StageInstance.objects.create(
        case=locked_case,
        stage_type=next_stage_type,
        sequence_number=prev_stage.sequence_number + 1,
        iteration_number=next_iter,
        status=StageStatus.IN_PROGRESS,
        assigned_officer=prev_stage.assigned_officer,
        assigned_committee=prev_stage.assigned_committee,
        started_at=now,
    )

    from apps.policy.runtime import create_stage_deadline
    create_stage_deadline(locked_case, new_stage, now)

    old_ver = locked_case.version
    new_ver = old_ver + 1
    locked_case.prescribed_stages = prescribed
    locked_case.status = CaseStatus.IN_STAGE_PROCESSING
    locked_case.current_stage_type = next_stage_type
    locked_case.version = new_ver
    locked_case.save(
        update_fields=["prescribed_stages", "status", "current_stage_type", "version", "updated_at"]
    )

    record_audit_event(
        actor=actor,
        actor_role=RoleCode.INSTITUTION_USER,
        actor_scope=scope.to_audit_dict(),
        action="DEFICIENCY_RESPONSE_SUBMITTED",
        target_type="ApplicationCase",
        target_id=str(locked_case.id),
        case=locked_case,
        old_version=old_ver,
        new_version=new_ver,
        reason=response_text.strip(),
        inputs_snapshot={
            "deficiency_cycle_id": str(open_cycle.id),
            "new_stage_instance_id": str(new_stage.id),
            "next_stage_type": next_stage_type,
        },
    )
    return new_stage


@transaction.atomic
def close_processing_instance(
    *,
    actor: Any,
    case_id: Any,
    expected_version: int,
    reason: str = "Close processing instance after disposition (Sheet 02 C4)",
) -> ApplicationCase:
    """Sheet 02 C4: Close this processing instance; retain case history; open obligations keep independent status and monitoring."""
    scope = resolve_actor_scope(actor)
    locked_case = ApplicationCase.objects.select_for_update().get(pk=case_id)
    if locked_case.version != expected_version:
        from apps.decisions.services import StaleCaseVersionError

        raise StaleCaseVersionError(f"Stale case version: expected {expected_version}, actual {locked_case.version}.")

    check_case_read_access(actor, locked_case)
    rule = validate_case_transition(
        case=locked_case,
        action="CLOSE_PROCESSING_INSTANCE",
        actor_roles=scope.roles,
    )
    old_ver = locked_case.version
    new_ver = old_ver + 1
    locked_case.status = rule.destination_status
    locked_case.closed_at = timezone.now()
    locked_case.version = new_ver
    locked_case.save(update_fields=["status", "closed_at", "version", "updated_at"])

    record_audit_event(
        actor=actor,
        actor_role=",".join(sorted(scope.roles)),
        actor_scope=scope.to_audit_dict(),
        action="CLOSE_PROCESSING_INSTANCE",
        target_type="ApplicationCase",
        target_id=str(locked_case.id),
        case=locked_case,
        old_version=old_ver,
        new_version=new_ver,
        reason=reason,
    )
    return locked_case


@transaction.atomic
def initiate_appeal_or_reopening(
    *,
    actor: Any,
    origin_case_id: Any,
    appeal_reason: str,
    designated_stages: list[str] | None = None,
) -> ApplicationCase:
    """Sheet 02 C4 detached box & Sheet 06 K6: Appeal / reopening as an authorised linked processing instance (-> A2 or designated B1 stage, e.g. SAC per APH 1.11 / 2.24)."""
    scope = resolve_actor_scope(actor)
    origin_case = ApplicationCase.objects.select_for_update().get(pk=origin_case_id)
    check_case_read_access(actor, origin_case)

    allowed = {RoleCode.INSTITUTION_USER, RoleCode.BUREAU_OFFICER, RoleCode.COMPETENT_AUTHORITY}
    if not (scope.roles & allowed):
        raise PermissionDenied("Actor is not authorised to initiate an appeal or reopening.")
    if origin_case.status not in {
        CaseStatus.DEFICIENCY_LETTER_LOD,
        CaseStatus.REJECTED_LOR,
        CaseStatus.CLOSED,
    }:
        raise TransitionViolationError(
            f"Appeal/reopening requires a completed disposition (LoD/LoR/Closed), current state is '{origin_case.status}'."
        )
    if not appeal_reason or not appeal_reason.strip():
        raise ValidationError("Appeal/reopening requires a recorded reason.")

    stages = designated_stages or [StageType.SAC]
    first_stage_type = stages[0]
    now = timezone.now()

    appeal_case = ApplicationCase.objects.create(
        case_number=f"{origin_case.case_number}-APPEAL-{origin_case.linked_appeals_or_reopenings.count() + 1}",
        source_id=f"{origin_case.source_id}:APPEAL:{uuid.uuid4().hex[:6]}",
        institution=origin_case.institution,
        region=origin_case.region,
        responsible_bureau=origin_case.responsible_bureau,
        academic_cycle=origin_case.academic_cycle,
        application_category=f"APPEAL_{origin_case.application_category}",
        programme_level=origin_case.programme_level,
        requested_courses=origin_case.requested_courses,
        input_snapshot=origin_case.input_snapshot,
        pinned_policy_version=origin_case.pinned_policy_version,
        selected_route_code="APPEAL_SAC_ROUTE",
        prescribed_stages=stages,
        status=CaseStatus.IN_STAGE_PROCESSING,
        current_stage_type=first_stage_type,
        parent_case=origin_case,
        submitted_at=now,
        version=1,
    )

    StageInstance.objects.create(
        case=appeal_case,
        stage_type=first_stage_type,
        sequence_number=1,
        iteration_number=1,
        status=StageStatus.IN_PROGRESS,
        started_at=now,
    )

    record_audit_event(
        actor=actor,
        actor_role=",".join(sorted(scope.roles)),
        actor_scope=scope.to_audit_dict(),
        action="APPEAL_LINKED_INSTANCE_CREATED",
        target_type="ApplicationCase",
        target_id=str(appeal_case.id),
        case=appeal_case,
        old_version=0,
        new_version=1,
        reason=appeal_reason.strip(),
        inputs_snapshot={
            "origin_case_id": str(origin_case.id),
            "designated_stages": stages,
        },
    )
    return appeal_case
