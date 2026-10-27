"""Deadlines, revision history, durable due-work scans (including 24h downtime catch-up), and multi-level escalations (Sheet 01 Block 06, Sheet 03 D2-D4, Sheet 04 H1-H5, Sheet 06 M6, Sheet 07 N3)."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.access.models import RoleAssignment, RoleCode
from apps.access.services import resolve_actor_scope
from apps.audit.services import record_audit_event
from apps.deadlines.models import DeadlineRecord, DeadlineRevision, DeadlineState
from apps.escalation.models import EscalationState, EscalationTask
from apps.notifications.models import DeliveryChannel, DeliveryOutcomeState, LogicalAlert
from apps.outbox.models import OutboxEvent, OutboxState


@transaction.atomic
def extend_or_hold_deadline(
    *,
    actor: Any,
    deadline_id: Any,
    new_due_at: timezone.datetime,
    reason: str,
    action_type: str = "EXTENSION",
) -> DeadlineRecord:
    """Sheet 01 Block 06 & Sheet 03 D4: Authorised deadline extension or hold preserves old deadline, reason, approver, and revision; supersedes stale queued outbox alerts."""
    scope = resolve_actor_scope(actor)
    allowed = {RoleCode.COMPETENT_AUTHORITY, RoleCode.BUREAU_OFFICER, RoleCode.REGIONAL_OFFICER}
    if not (scope.roles & allowed):
        raise PermissionDenied("Deadline extension or hold requires regulatory authority (Sheet 03 D4, Sheet 07 P5).")
    if not reason or not reason.strip():
        raise ValidationError("Deadline extension or hold requires an explicit recorded reason (Sheet 03 D4).")

    dl = DeadlineRecord.objects.select_for_update().get(pk=deadline_id)
    if RoleCode.REGIONAL_OFFICER in scope.roles and dl.region_id not in scope.region_ids:
        raise PermissionDenied("Regional officer cannot extend deadlines outside their region.")
    if new_due_at <= dl.due_at and action_type == "EXTENSION":
        raise ValidationError("Extended due date must be later than current due_at.")

    old_due = dl.due_at
    old_rev = dl.current_revision
    new_rev = old_rev + 1

    DeadlineRevision.objects.create(
        deadline=dl,
        revision_number=new_rev,
        previous_due_at=old_due,
        new_due_at=new_due_at,
        action_type=action_type,
        reason=reason.strip(),
        approved_by=actor,
    )

    dl.due_at = new_due_at
    dl.current_revision = new_rev
    if action_type == "HOLD":
        dl.state = DeadlineState.ON_HOLD
    dl.save(update_fields=["due_at", "current_revision", "state", "updated_at"])

    # Supersede any pending unsent outbox events tied to the old revision (Sheet 04 H1, Sheet 06 M1, Sheet 07 Q3)
    OutboxEvent.objects.filter(
        deadline=dl,
        deadline_revision=old_rev,
        state=OutboxState.PENDING,
    ).update(state=OutboxState.SUPERSEDED_CANCELLED)

    record_audit_event(
        actor=actor,
        actor_role=",".join(sorted(scope.roles)),
        actor_scope=scope.to_audit_dict(),
        action=f"DEADLINE_{action_type}",
        target_type="DeadlineRecord",
        target_id=str(dl.id),
        case=dl.case,
        institution=dl.institution,
        region=dl.region,
        old_version=old_rev,
        new_version=new_rev,
        reason=reason.strip(),
        inputs_snapshot={
            "previous_due_at": old_due.isoformat(),
            "new_due_at": new_due_at.isoformat(),
            "action_type": action_type,
        },
    )
    return dl


def _resolve_recipient_for_deadline(dl: DeadlineRecord, target_role: str | None = None) -> Any:
    """Resolve user recipient for an institution or officer deadline/escalation."""
    if dl.owner_user_id and target_role is None:
        return dl.owner_user

    from django.db.models import Q
    role_to_find = target_role or dl.owner_role
    now = timezone.now()
    ra_qs = RoleAssignment.objects.filter(role=role_to_find, is_active=True, user__is_active=True, valid_from__lte=now).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=now)).select_related("user")
    if role_to_find == RoleCode.INSTITUTION_USER:
        ra_qs = ra_qs.filter(institution=dl.institution)
    elif role_to_find == RoleCode.REGIONAL_OFFICER:
        ra_qs = ra_qs.filter(region=dl.region)
    elif role_to_find == RoleCode.BUREAU_OFFICER:
        bureau_id = dl.case.responsible_bureau_id if dl.case_id else None
        ra_qs = ra_qs.filter(Q(region=dl.region) | Q(bureau_id=bureau_id)) if bureau_id else ra_qs.filter(region=dl.region)
    elif role_to_find != RoleCode.COMPETENT_AUTHORITY:
        return None
    assignment = ra_qs.order_by("created_at", "id").first()
    return assignment.user if assignment else None


def scan_durable_due_work_register(
    *,
    now: timezone.datetime | None = None,
    escalation_levels_config: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Sheet 04 H1-H2 & Sheet 05 CELERY BEAT: Scan durable due-work register across all eligible active deadlines, including missed intervals after scheduler downtime.

    - Deduplicates logical alerts by (deadline, current_revision, milestone_code, recipient, channel).
    - Creates multi-level EscalationTask in order when overdue thresholds are reached, stopping if escalation is already closed or deadline completed.
    """
    current_time = now or timezone.now()
    levels = escalation_levels_config or [
        {"level": 1, "overdue_hours": 0, "target_role": RoleCode.REGIONAL_OFFICER},
        {"level": 2, "overdue_hours": 24, "target_role": RoleCode.BUREAU_OFFICER},
        {"level": 3, "overdue_hours": 72, "target_role": RoleCode.COMPETENT_AUTHORITY},
    ]

    active_deadlines = list(
        DeadlineRecord.objects.filter(state=DeadlineState.ACTIVE).select_related(
            "institution", "region", "case", "owner_user"
        )
    )

    alerts_created = 0
    escalations_created = 0

    for dl in active_deadlines:
        with transaction.atomic():
            locked_dl = DeadlineRecord.objects.select_for_update().get(pk=dl.pk)
            if locked_dl.state != DeadlineState.ACTIVE:
                continue

            # 1. Check reminder offsets (including any missed during scheduler downtime)
            for offset_h in sorted(locked_dl.reminder_offsets_hours or [], reverse=True):
                threshold_time = locked_dl.due_at - timedelta(hours=int(offset_h))
                if current_time >= threshold_time:
                    milestone_code = f"REMINDER_{int(offset_h)}H" if int(offset_h) > 0 else "DUE_NOW"
                    recipient = _resolve_recipient_for_deadline(locked_dl)
                    if recipient is None:
                        continue
                    alert, created = LogicalAlert.objects.get_or_create(
                        deadline=locked_dl,
                        deadline_revision=locked_dl.current_revision,
                        milestone_code=milestone_code,
                        recipient=recipient,
                        channel=DeliveryChannel.IN_APP,
                        defaults={
                            "case": locked_dl.case,
                            "institution": locked_dl.institution,
                            "subject": f"[{milestone_code}] {locked_dl.source_type} due at {locked_dl.due_at.isoformat()}",
                            "body": f"Deadline for {locked_dl.source_type} ({locked_dl.clock_type}) reached milestone {milestone_code}.",
                            "outcome_state": DeliveryOutcomeState.PENDING,
                        },
                    )
                    if created:
                        alerts_created += 1
                        OutboxEvent.objects.get_or_create(
                            logical_id=f"alert:{alert.id}",
                            defaults={
                                "event_type": "DELIVER_ALERT",
                                "case": locked_dl.case,
                                "deadline": locked_dl,
                                "deadline_revision": locked_dl.current_revision,
                                "payload": {"logical_alert_id": str(alert.id)},
                                "state": OutboxState.PENDING,
                                "next_attempt_at": current_time,
                            },
                        )

            # 2. Check multi-level escalations if overdue (Sheet 03 D3, Sheet 04 H2/H5, PS Section F)
            if current_time >= locked_dl.due_at:
                overdue_hours = (current_time - locked_dl.due_at).total_seconds() / 3600.0

                # If an escalation for this deadline revision was already explicitly CLOSED by authorised action, stop firing further escalations (MINIMUM TESTS: "escalation levels fire in order and stop on closure")
                has_closed_escalation = EscalationTask.objects.filter(
                    deadline=locked_dl,
                    deadline_revision=locked_dl.current_revision,
                    state=EscalationState.CLOSED,
                ).exists()
                if has_closed_escalation:
                    continue

                policy = locked_dl.case.pinned_policy_version if locked_dl.case_id else None
                configured_levels = (policy.escalation_hierarchies or {}).get("levels") if policy else None
                effective_levels = escalation_levels_config if escalation_levels_config is not None else (configured_levels if configured_levels is not None else levels)
                for lvl_spec in sorted(effective_levels, key=lambda x: int(x["level"])):
                    lvl_num = int(lvl_spec["level"])
                    req_hours = float(lvl_spec["overdue_hours"])
                    target_role = str(lvl_spec["target_role"])

                    if overdue_hours < req_hours:
                        break

                    owner_user = _resolve_recipient_for_deadline(locked_dl, target_role=target_role)
                    if owner_user is None:
                        continue

                    try:
                        esc, esc_created = EscalationTask.objects.get_or_create(
                            deadline=locked_dl,
                            deadline_revision=locked_dl.current_revision,
                            escalation_level=lvl_num,
                            defaults={
                                "case": locked_dl.case,
                                "institution": locked_dl.institution,
                                "region": locked_dl.region,
                                "target_role": target_role,
                                "owner": owner_user,
                                "trigger_reason": f"Overdue by {overdue_hours:.1f}h (threshold {req_hours}h) at Level {lvl_num}",
                                "state": EscalationState.OPEN,
                            },
                        )
                    except IntegrityError:
                        esc_created = False

                    if esc_created:
                        escalations_created += 1
                        # Mark previous lower-level open escalations as ESCALATED_NEXT_LEVEL
                        EscalationTask.objects.filter(
                            deadline=locked_dl,
                            deadline_revision=locked_dl.current_revision,
                            escalation_level__lt=lvl_num,
                            state=EscalationState.OPEN,
                        ).update(state=EscalationState.ESCALATED_NEXT_LEVEL)

                        alert, al_created = LogicalAlert.objects.get_or_create(
                            deadline=locked_dl,
                            deadline_revision=locked_dl.current_revision,
                            milestone_code=f"ESCALATION_L{lvl_num}",
                            recipient=owner_user,
                            channel=DeliveryChannel.IN_APP,
                            defaults={
                                "case": locked_dl.case,
                                "institution": locked_dl.institution,
                                "subject": f"[ESCALATION L{lvl_num}] Overdue {locked_dl.source_type}",
                                "body": esc.trigger_reason,
                                "outcome_state": DeliveryOutcomeState.PENDING,
                            },
                        )
                        if al_created:
                            alerts_created += 1
                            OutboxEvent.objects.get_or_create(
                                logical_id=f"alert:{alert.id}",
                                defaults={
                                    "event_type": "DELIVER_ALERT",
                                    "case": locked_dl.case,
                                    "deadline": locked_dl,
                                    "deadline_revision": locked_dl.current_revision,
                                    "payload": {"logical_alert_id": str(alert.id), "escalation_id": str(esc.id)},
                                    "state": OutboxState.PENDING,
                                    "next_attempt_at": current_time,
                                },
                            )

    return {
        "scanned_at": current_time.isoformat(),
        "active_deadlines_scanned": len(active_deadlines),
        "alerts_created": alerts_created,
        "escalations_created": escalations_created,
    }


@transaction.atomic
def close_escalation_task(
    *,
    actor: Any,
    escalation_id: Any,
    closure_reason: str,
) -> EscalationTask:
    """Sheet 04 H5 & Sheet 06 M6: Escalation ownership remains open until closed by authorised action (a sent email is not case/escalation closure)."""
    scope = resolve_actor_scope(actor)
    allowed = {RoleCode.REGIONAL_OFFICER, RoleCode.BUREAU_OFFICER, RoleCode.COMPETENT_AUTHORITY}
    if not (scope.roles & allowed):
        raise PermissionDenied("Actor is not authorised to close an escalation task (Sheet 04 H5).")
    if not closure_reason or not closure_reason.strip():
        raise ValidationError("Closing an escalation requires a recorded closure_reason (Sheet 04 H5).")

    esc = EscalationTask.objects.select_for_update().get(pk=escalation_id)
    if RoleCode.REGIONAL_OFFICER in scope.roles and esc.region_id not in scope.region_ids:
        raise PermissionDenied("Regional officer cannot close escalations outside their region.")

    now = timezone.now()
    # Close this escalation and any lower-level escalations for the same deadline revision
    EscalationTask.objects.filter(
        deadline_id=esc.deadline_id,
        deadline_revision=esc.deadline_revision,
    ).exclude(state=EscalationState.CLOSED).update(
        state=EscalationState.CLOSED,
        closed_by=actor,
        closed_at=now,
        closure_reason=closure_reason.strip(),
    )
    esc.refresh_from_db()

    record_audit_event(
        actor=actor,
        actor_role=",".join(sorted(scope.roles)),
        actor_scope=scope.to_audit_dict(),
        action="ESCALATION_CLOSED",
        target_type="EscalationTask",
        target_id=str(esc.id),
        case=esc.case,
        institution=esc.institution,
        region=esc.region,
        reason=closure_reason.strip(),
        inputs_snapshot={
            "deadline_id": str(esc.deadline_id),
            "deadline_revision": esc.deadline_revision,
            "escalation_level": esc.escalation_level,
        },
    )
    return esc
