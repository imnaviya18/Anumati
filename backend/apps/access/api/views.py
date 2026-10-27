"""API views for role assignments and case/stage assignments with validity periods (PS Administration, Sheet 07 N1, P5)."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access.models import RoleAssignment, RoleCode
from apps.access.services import assign_role_to_user, resolve_actor_scope
from apps.organisation.models import Bureau, Committee, Institution, Region

User = get_user_model()


class RoleAssignmentAdminView(APIView):
    """List or create scoped role assignments with validity windows (Sheet 07 N1, P5)."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            scope = resolve_actor_scope(request.user)
            if not (
                scope.roles
                & {
                    RoleCode.TECHNICAL_ADMIN,
                    RoleCode.OVERSIGHT_AUDITOR,
                    RoleCode.COMPETENT_AUTHORITY,
                }
            ):
                return Response({"detail": "Denied."}, status=status.HTTP_403_FORBIDDEN)
            qs = RoleAssignment.objects.select_related(
                "user", "institution", "region", "bureau", "committee"
            ).all()[:200]
            return Response(
                [
                    {
                        "id": str(ra.id),
                        "username": ra.user.username,
                        "role": ra.role,
                        "institution_code": ra.institution.permanent_id
                        if ra.institution
                        else None,
                        "region_code": ra.region.code if ra.region else None,
                        "bureau_code": ra.bureau.code if ra.bureau else None,
                        "committee_code": ra.committee.code if ra.committee else None,
                        "delegated_powers": ra.delegated_powers,
                        "valid_from": ra.valid_from.isoformat(),
                        "valid_until": ra.valid_until.isoformat()
                        if ra.valid_until
                        else None,
                        "is_active": ra.is_active,
                    }
                    for ra in qs
                ]
            )
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

    def post(self, request: Request) -> Response:
        target_user = get_object_or_404(User, id=request.data.get("user_id"))
        inst = (
            get_object_or_404(Institution, id=request.data["institution_id"])
            if request.data.get("institution_id")
            else None
        )
        reg = (
            get_object_or_404(Region, id=request.data["region_id"])
            if request.data.get("region_id")
            else None
        )
        bur = (
            get_object_or_404(Bureau, id=request.data["bureau_id"])
            if request.data.get("bureau_id")
            else None
        )
        com = (
            get_object_or_404(Committee, id=request.data["committee_id"])
            if request.data.get("committee_id")
            else None
        )
        from django.utils.dateparse import parse_datetime
        from django.utils import timezone

        dates = {}
        for field in ("valid_from", "valid_until"):
            if request.data.get(field):
                value = parse_datetime(str(request.data[field]))
                if value is None or timezone.is_naive(value):
                    raise ValidationError(f"{field} must include a timezone.")
                dates[field] = value
        try:
            ra = assign_role_to_user(
                actor=request.user,
                target_user=target_user,
                role=str(request.data.get("role", "")),
                reason=str(request.data.get("reason", "")),
                institution=inst,
                region=reg,
                bureau=bur,
                committee=com,
                delegated_powers=request.data.get("delegated_powers") or [],
                **dates,
            )
            return Response(
                {"id": str(ra.id), "role": ra.role}, status=status.HTTP_201_CREATED
            )
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class CaseAssignmentView(APIView):
    def post(self, request):
        from apps.cases.models import ApplicationCase, StageInstance
        from apps.access.services import create_case_assignment

        case = get_object_or_404(ApplicationCase, id=request.data.get("case_id"))
        stage = (
            get_object_or_404(StageInstance, id=request.data["stage_id"], case=case)
            if request.data.get("stage_id")
            else None
        )
        user = (
            get_object_or_404(User, id=request.data["user_id"])
            if request.data.get("user_id")
            else None
        )
        committee = (
            get_object_or_404(Committee, id=request.data["committee_id"])
            if request.data.get("committee_id")
            else None
        )
        assignment = create_case_assignment(
            actor=request.user,
            case=case,
            stage_instance=stage,
            target_user=user,
            target_committee=committee,
            assignment_scope=str(
                request.data.get("assignment_scope", "STAGE_REVIEWER")
            ),
            reason=str(request.data.get("reason", "")),
        )
        return Response({"id": str(assignment.id)}, status=201)


class RevokeAssignmentView(APIView):
    def post(self, request, assignment_id):
        from django.db import transaction
        from apps.audit.services import record_audit_event

        scope = resolve_actor_scope(request.user)
        if RoleCode.TECHNICAL_ADMIN not in scope.roles:
            raise PermissionDenied(
                "Only technical administrators can revoke role assignments."
            )
        reason = str(request.data.get("reason", "")).strip()
        if not reason:
            raise ValidationError("A revocation reason is required.")
        with transaction.atomic():
            assignment = get_object_or_404(
                RoleAssignment.objects.select_for_update(), id=assignment_id
            )
            assignment.is_active = False
            assignment.save(update_fields=["is_active", "updated_at"])
            record_audit_event(
                actor=request.user,
                actor_role="TECHNICAL_ADMIN",
                actor_scope=scope.to_audit_dict(),
                action="ROLE_ASSIGNMENT_REVOKED",
                target_type="RoleAssignment",
                target_id=str(assignment.id),
                reason=reason,
            )
        return Response({"id": str(assignment.id), "is_active": False})


class AssignmentOptionsView(APIView):
    def get(self, request):
        from apps.access.selectors import scope_cases_queryset
        from apps.cases.models import ApplicationCase
        scope = resolve_actor_scope(request.user)
        if not scope.roles & {"TECHNICAL_ADMIN","REGIONAL_OFFICER","BUREAU_OFFICER","COMPETENT_AUTHORITY"}:
            raise PermissionDenied("Case assignment authority is required.")
        cases = ApplicationCase.objects.all() if "TECHNICAL_ADMIN" in scope.roles else scope_cases_queryset(request.user)
        cases = cases.exclude(status="CLOSED").select_related("institution").prefetch_related("stage_instances").order_by('-created_at')[:200]
        selected = next((c for c in cases if str(c.id)==request.query_params.get('case_id')),None)
        candidates=[]
        if selected:
            for user in User.objects.filter(is_active=True).order_by('username')[:200]:
                try:
                    candidate=resolve_actor_scope(user)
                except PermissionDenied:
                    continue
                if not candidate.roles & {"SCRUTINY_MEMBER","EVC_MEMBER","COMMITTEE_MEMBER","REGIONAL_OFFICER","BUREAU_OFFICER","COMPETENT_AUTHORITY"}:
                    continue
                if "REGIONAL_OFFICER" in candidate.roles and selected.region_id not in candidate.region_ids:
                    continue
                if "BUREAU_OFFICER" in candidate.roles and selected.region_id not in candidate.region_ids and selected.responsible_bureau_id not in candidate.bureau_ids:
                    continue
                candidates.append({"id":user.pk,"username":user.username})
        return Response({"cases":[{"id":str(c.id),"case_number":c.case_number,"institution":c.institution.name,"stages":[{"id":str(s.id),"stage_type":s.stage_type,"status":s.status} for s in c.stage_instances.all() if s.status in {'PENDING','IN_PROGRESS'}]} for c in cases],"reviewers":candidates})
