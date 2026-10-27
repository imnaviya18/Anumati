"""API views for cases, intake, route resolution, stage transitions, and deficiency responses (Sheets 02, 06)."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access.selectors import scope_cases_queryset
from apps.access.services import check_case_read_access
from apps.cases.models import ApplicationCase, StageInstance, DeficiencyCycle
from apps.cases.services import (
    resolve_and_dispatch_case_route,
    submit_deficiency_response,
    submit_or_import_application,
)
from apps.common.pagination import StandardResultsSetPagination
from apps.decisions.services import (
    IdempotencyConflictError,
    StaleCaseVersionError,
    execute_guarded_stage_transition_command,
)
from apps.organisation.models import Bureau, Institution
from apps.policy.models import PolicyVersion
from apps.routing.services import TransitionViolationError


def _serialize_case(c: ApplicationCase) -> dict:
    return {
        "id": str(c.id),
        "case_number": c.case_number,
        "source_id": c.source_id,
        "institution_id": str(c.institution_id),
        "institution_code": c.institution.permanent_id,
        "institution_name": c.institution.name,
        "region_id": str(c.region_id),
        "region_code": c.region.code,
        "academic_cycle": c.academic_cycle,
        "application_category": c.application_category,
        "selected_route_code": c.selected_route_code,
        "is_demonstration": c.pinned_policy_version.is_demonstration if c.pinned_policy_version_id else None,
        "prescribed_stages": c.prescribed_stages,
        "status": c.status,
        "current_stage_type": c.current_stage_type,
        "version": c.version,
        "submitted_at": c.submitted_at.isoformat() if c.submitted_at else None,
        "closed_at": c.closed_at.isoformat() if c.closed_at else None,
    }


class CaseListIntakeView(APIView):
    """List scoped cases with pagination/search, or submit/import a new application (Sheet 02 A1, Sheet 07 Q2)."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            qs = scope_cases_queryset(
                request.user,
                ApplicationCase.objects.select_related(
                    "institution", "region", "responsible_bureau", "pinned_policy_version"
                ),
            )
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        search = request.query_params.get("q", "").strip()
        if search:
            qs = qs.filter(case_number__icontains=search) | qs.filter(
                institution__permanent_id__icontains=search
            )
        status_filter = request.query_params.get("status", "").strip()
        if status_filter:
            qs = qs.filter(status=status_filter)

        for param, field in [("region_code", "region__code"), ("bureau_code", "responsible_bureau__code")]:
            if request.query_params.get(param):
                qs = qs.filter(**{field:request.query_params[param]})
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(qs.order_by("-created_at"), request)
        data = [_serialize_case(c) for c in page]
        return paginator.get_paginated_response(data)

    def post(self, request: Request) -> Response:
        try:
            inst = get_object_or_404(Institution, id=request.data.get("institution_id"))
            bureau = (
                Bureau.objects.filter(
                    id=request.data.get("responsible_bureau_id")
                ).first()
                if request.data.get("responsible_bureau_id")
                else None
            )
            case = submit_or_import_application(
                actor=request.user,
                institution=inst,
                source_id=str(request.data.get("source_id", "")),
                academic_cycle=str(request.data.get("academic_cycle", "")),
                application_category=str(request.data.get("application_category", "")),
                programme_level=str(
                    request.data.get("programme_level", "UNDER_GRADUATE")
                ),
                requested_courses=request.data.get("requested_courses") or [],
                input_snapshot=request.data.get("input_snapshot") or {},
                responsible_bureau=bureau,
            )
            return Response(_serialize_case(case), status=status.HTTP_201_CREATED)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class CaseDetailView(APIView):
    """Retrieve a single case with strict scope verification (Sheet 07 Q2)."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, case_id: str) -> Response:
        case = get_object_or_404(
            ApplicationCase.objects.select_related(
                "institution", "region", "responsible_bureau", "pinned_policy_version"
            ),
            id=case_id,
        )
        try:
            check_case_read_access(request.user, case)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        stages = [
            {
                "id": str(si.id),
                "stage_type": si.stage_type,
                "sequence_number": si.sequence_number,
                "iteration_number": si.iteration_number,
                "status": si.status,
                "recommendation": si.recommendation,
                "findings": si.findings,
                "completion_reason": si.completion_reason,
            }
            for si in case.stage_instances.all()
        ]
        from apps.cases.workspace import available_actions
        payload = _serialize_case(case)
        payload["available_actions"] = available_actions(request.user,case)
        payload["stage_instances"] = stages
        payload["deficiency_history"] = list(case.deficiency_cycles.values("id", "deficiencies_recorded", "institution_response", "response_evidence_ids", "responded_at"))
        payload["deficiency_cycles"] = list(
            case.deficiency_cycles.filter(responded_at__isnull=True).values(
                "id", "deficiencies_recorded"
            )
        )
        return Response(payload)


class CaseRouteResolveView(APIView):
    """Resolve and dispatch policy route for a submitted/review-required case (Sheet 02 A2-A4)."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, case_id: str) -> Response:
        case = get_object_or_404(ApplicationCase, id=case_id)
        policy = None
        if request.data.get("policy_id"):
            policy = get_object_or_404(PolicyVersion, id=request.data["policy_id"])
        try:
            updated = resolve_and_dispatch_case_route(
                actor=request.user,
                case=case,
                reason=str(request.data.get("reason", "Resolve route via API")),
                explicit_policy=policy,
            )
            return Response(_serialize_case(updated))
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class CaseStageTransitionView(APIView):
    """Execute guarded stage transition command with expected_version and idempotency_key (Sheet 06 K1-K6)."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, case_id: str, stage_instance_id: str) -> Response:
        case = get_object_or_404(ApplicationCase, id=case_id)
        stage_instance = get_object_or_404(
            StageInstance, id=stage_instance_id, case=case
        )
        try:
            res = execute_guarded_stage_transition_command(
                actor=request.user,
                case_id=case.id,
                stage_instance_id=stage_instance.id,
                action=str(request.data.get("action", "")),
                expected_version=int(request.data.get("expected_version", 0)),
                idempotency_key=str(request.data.get("idempotency_key", "")),
                reason=str(request.data.get("reason", "")),
                findings=request.data.get("deficiencies")
                or request.data.get("findings")
                or [],
                recommendation=str(request.data.get("recommendation", "")),
            )
            return Response(res.body, status=res.status_code)
        except (StaleCaseVersionError, IdempotencyConflictError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except (TransitionViolationError, ValidationError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class DeficiencyResponseView(APIView):
    """Submit institution deficiency clarification response (Sheet 02 B2)."""

    permission_classes = [IsAuthenticated]

    def post(
        self, request: Request, case_id: str, deficiency_cycle_id: str
    ) -> Response:
        case = get_object_or_404(ApplicationCase, id=case_id)
        get_object_or_404(
            DeficiencyCycle,
            id=deficiency_cycle_id,
            case=case,
            responded_at__isnull=True,
        )
        try:
            submit_deficiency_response(
                actor=request.user,
                case_id=case.id,
                expected_version=int(request.data.get("expected_version", 0)),
                response_text=str(request.data.get("response_text", "")),
                response_evidence_ids=request.data.get("evidence_version_ids") or [],
            )
            case.refresh_from_db()
            return Response(_serialize_case(case))
        except StaleCaseVersionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class CaseLifecycleView(APIView):
    def post(self, request, case_id, action):
        from apps.cases.services import (
            close_processing_instance,
            initiate_appeal_or_reopening,
        )

        case = get_object_or_404(ApplicationCase, id=case_id)
        check_case_read_access(request.user, case)
        reason = str(request.data.get("reason", "")).strip()
        if not reason:
            raise ValidationError("A recorded reason is required.")
        try:
            if action == "close":
                updated = close_processing_instance(
                    actor=request.user,
                    case_id=case.id,
                    expected_version=int(request.data.get("expected_version", 0)),
                    reason=reason,
                )
            elif action == "appeal":
                updated = initiate_appeal_or_reopening(
                    actor=request.user, origin_case_id=case.id, appeal_reason=reason
                )
            else:
                raise ValidationError("Unknown lifecycle action.")
        except StaleCaseVersionError as exc:
            return Response({"detail": str(exc)}, status=409)
        except TransitionViolationError as exc:
            raise ValidationError(str(exc)) from exc
        return Response(_serialize_case(updated))
