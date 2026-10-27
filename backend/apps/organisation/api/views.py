"""API views for local administration of regions, bureaus, institutions, committees, and memberships (PS Administration)."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access.models import RoleCode
from apps.access.services import resolve_actor_scope
from apps.organisation.models import Bureau, Committee, Institution, Region
from apps.organisation.services import (
    create_bureau,
    create_committee,
    create_institution,
    create_region,
)


def _assert_admin(request: Request) -> None:
    scope = resolve_actor_scope(request.user)
    if not (
        scope.roles
        & {
            RoleCode.TECHNICAL_ADMIN,
            RoleCode.BUREAU_OFFICER,
            RoleCode.COMPETENT_AUTHORITY,
        }
    ):
        raise PermissionDenied(
            "Organisation administration requires authorised administrative role."
        )


class OrganisationSummaryAdminView(APIView):
    """List or create Regions, Bureaus, Institutions, and Committees (PS Administration)."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            scope = resolve_actor_scope(request.user)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        institutions = Institution.objects.select_related("region").filter(
            is_active=True
        )
        if not (
            scope.roles
            & {
                RoleCode.TECHNICAL_ADMIN,
                RoleCode.COMPETENT_AUTHORITY,
                RoleCode.OVERSIGHT_AUDITOR,
            }
        ):
            from django.db.models import Q

            institutions = institutions.filter(
                Q(id__in=scope.institution_ids) | Q(region_id__in=scope.region_ids)
            )
        return Response(
            {
                "regions": [
                    {
                        "id": str(r.id),
                        "code": r.code,
                        "name": r.name,
                        "headquarters": r.headquarters_city,
                    }
                    for r in Region.objects.filter(is_active=True)
                ],
                "bureaus": [
                    {"id": str(b.id), "code": b.code, "name": b.name}
                    for b in Bureau.objects.filter(is_active=True)
                ],
                "institutions": [
                    {
                        "id": str(i.id),
                        "code": i.permanent_id,
                        "name": i.name,
                        "region_code": i.region.code,
                        "category": i.category,
                        "is_new_institution": i.is_new_institution,
                    }
                    for i in institutions[:200]
                ],
                "committees": [
                    {
                        "id": str(c.id),
                        "code": c.code,
                        "name": c.name,
                        "committee_type": c.committee_type,
                    }
                    for c in Committee.objects.filter(is_active=True)
                ],
            }
        )

    def post(self, request: Request) -> Response:
        try:
            _assert_admin(request)
            entity_type = str(request.data.get("entity_type", "")).upper()
            if entity_type == "REGION":
                reg = create_region(
                    actor=request.user,
                    code=str(request.data.get("code", "")),
                    name=str(request.data.get("name", "")),
                    headquarters_city=str(request.data.get("headquarters", "")),
                    states_covered=request.data.get("states_covered") or [],
                )
                return Response(
                    {"id": str(reg.id), "code": reg.code},
                    status=status.HTTP_201_CREATED,
                )
            if entity_type == "BUREAU":
                bur = create_bureau(
                    actor=request.user,
                    code=str(request.data.get("code", "")),
                    name=str(request.data.get("name", "")),
                    bureau_type=str(request.data.get("bureau_type", "REGULATION")),
                )
                return Response(
                    {"id": str(bur.id), "code": bur.code},
                    status=status.HTTP_201_CREATED,
                )
            if entity_type == "INSTITUTION":
                reg = get_object_or_404(Region, id=request.data.get("region_id"))
                inst = create_institution(
                    actor=request.user,
                    permanent_id=str(request.data.get("code", "")),
                    name=str(request.data.get("name", "")),
                    region=reg,
                    state=str(request.data.get("state_name", "")),
                    category=str(
                        request.data.get("category", "PRIVATE_SELF_FINANCING")
                    ),
                    is_new_institution=bool(
                        request.data.get("is_new_institution", False)
                    ),
                )
                return Response(
                    {"id": str(inst.id), "code": inst.permanent_id},
                    status=status.HTTP_201_CREATED,
                )
            if entity_type == "COMMITTEE":
                reg = (
                    get_object_or_404(Region, id=request.data["region_id"])
                    if request.data.get("region_id")
                    else None
                )
                com = create_committee(
                    actor=request.user,
                    code=str(request.data.get("code", "")),
                    name=str(request.data.get("name", "")),
                    committee_type=str(request.data.get("committee_type", "SCRUTINY")),
                    region=reg,
                    quorum_count=int(request.data.get("quorum_required", 2)),
                )
                return Response(
                    {"id": str(com.id), "code": com.code},
                    status=status.HTTP_201_CREATED,
                )
            return Response(
                {"detail": "Unknown entity_type."}, status=status.HTTP_400_BAD_REQUEST
            )
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class CommitteeMembershipView(APIView):
    def post(self, request):
        from django.contrib.auth import get_user_model
        from apps.organisation.services import add_committee_member

        committee = get_object_or_404(Committee, id=request.data.get("committee_id"))
        user = get_object_or_404(get_user_model(), id=request.data.get("user_id"))
        scope = resolve_actor_scope(request.user)
        if RoleCode.TECHNICAL_ADMIN not in scope.roles:
            if (
                RoleCode.REGIONAL_OFFICER in scope.roles
                and committee.region_id not in scope.region_ids
            ):
                raise PermissionDenied("Committee is outside assigned region.")
            if (
                RoleCode.BUREAU_OFFICER in scope.roles
                and committee.bureau_id not in scope.bureau_ids
            ):
                raise PermissionDenied("Committee is outside assigned bureau.")
        reason = str(request.data.get("reason", "")).strip()
        if not reason:
            raise ValidationError("A membership reason is required.")
        result = add_committee_member(
            actor=request.user,
            committee=committee,
            user=user,
            member_role=str(request.data.get("member_role", "ACADEMIC_EXPERT")),
            reason=reason,
        )
        return Response({"id": str(result.id)}, status=201)
