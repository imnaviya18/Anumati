from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from apps.access.selectors import scope_cases_queryset
from apps.access.services import check_case_read_access
from apps.cases.models import ApplicationCase, StageInstance
from apps.evc.models import EvcCoordination
from apps.evc.services import (
    check_evc_readiness_and_queue,
    reserve_evc_slot_atomically,
    confirm_or_reject_evc_schedule,
    reschedule_evc_visit,
    conduct_and_complete_evc_report,
)
from apps.decisions.services import StaleCaseVersionError, IdempotencyConflictError


def serialize(coord):
    return {
        "id": str(coord.id),
        "case_id": str(coord.case_id),
        "case_number": coord.case.case_number,
        "stage_instance_id": str(coord.stage_instance_id),
        "status": coord.status,
        "mode": coord.mode,
        "case_version": coord.case.version,
        "scheduled_start": coord.scheduled_start,
        "scheduled_end": coord.scheduled_end,
        "blocker_reason": coord.blocker_reason,
        "report_summary": coord.report_summary,
        "observations": coord.observations,
        "evidence_version_ids": coord.evidence_version_ids,
        "report_submitted_at": coord.report_submitted_at,
        "committee_id": str(coord.committee_id) if coord.committee_id else None,
    }


class EvcView(APIView):
    def get(self, request):
        qs = EvcCoordination.objects.filter(
            case__in=scope_cases_queryset(request.user)
        ).select_related("case")
        return Response([serialize(c) for c in qs[:100]])

    def post(self, request, coordination_id=None, action=None):
        d = request.data
        if coordination_id is None:
            case = get_object_or_404(ApplicationCase, id=d.get("case_id"))
            check_case_read_access(request.user, case)
            stage = get_object_or_404(
                StageInstance, id=d.get("stage_instance_id"), case=case
            )
            coord = check_evc_readiness_and_queue(
                actor=request.user,
                case_id=case.id,
                stage_instance_id=stage.id,
                mode=d.get("mode", "ONLINE"),
                reason=d.get("reason", "Readiness review"),
            )
            return Response(serialize(coord), status=201)
        coord = get_object_or_404(
            EvcCoordination.objects.select_related("case"), id=coordination_id
        )
        check_case_read_access(request.user, coord.case)
        reason = str(d.get("reason", "")).strip()
        if not reason:
            raise ValidationError("A recorded reason is required.")
        if action == "reserve":
            start = parse_datetime(str(d.get("slot_start", "")))
            end = parse_datetime(str(d.get("slot_end", "")))
            if (
                not start
                or not end
                or timezone.is_naive(start)
                or timezone.is_naive(end)
            ):
                raise ValidationError("Supply timezone-aware start and end timestamps.")
            reserve_evc_slot_atomically(
                actor=request.user,
                coordination_id=coord.id,
                committee_id=d.get("committee_id"),
                slot_start=start,
                slot_end=end,
                reason=reason,
            )
        elif action == "confirm":
            if not isinstance(d.get("confirmed"), bool):
                raise ValidationError("confirmed must be a boolean.")
            confirm_or_reject_evc_schedule(
                actor=request.user,
                coordination_id=coord.id,
                confirmed=d["confirmed"],
                reason=reason,
            )
        elif action == "reschedule":
            reschedule_evc_visit(
                actor=request.user, coordination_id=coord.id, reason=reason
            )
        elif action == "report":
            try:
                result = conduct_and_complete_evc_report(
                    actor=request.user,
                    coordination_id=coord.id,
                    expected_case_version=int(d.get("expected_version", 0)),
                    idempotency_key=str(d.get("idempotency_key", "")),
                    observations=d.get("observations") or {},
                    evidence_version_ids=d.get("evidence_version_ids") or [],
                    video_recording_ref=str(d.get("video_recording_ref", "")),
                    gps_coordinates=str(d.get("gps_coordinates", "")),
                    report_summary=reason,
                    recommendation=str(d.get("recommendation", "")),
                )
                return Response(result)
            except (StaleCaseVersionError, IdempotencyConflictError) as exc:
                return Response({"detail": str(exc)}, status=409)
        else:
            raise ValidationError("Unknown EVC action.")
        coord.refresh_from_db()
        return Response(serialize(coord))
