"""Domain services for organisation master data management with audit (PS Administration, Sheet 07 N1, P5)."""
from __future__ import annotations

from typing import Any
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.access.models import RoleCode
from apps.access.services import resolve_actor_scope
from apps.audit.services import record_audit_event
from apps.organisation.models import Bureau, Committee, CommitteeMembership, Institution, Region


def _require_admin_actor(actor: Any) -> Any:
    scope = resolve_actor_scope(actor)
    if RoleCode.TECHNICAL_ADMIN not in scope.roles:
        raise PermissionDenied("Only TECHNICAL_ADMIN can manage organisation master records.")
    return scope


@transaction.atomic
def create_region(
    *,
    actor: Any,
    code: str,
    name: str,
    headquarters_city: str = "",
    states_covered: list[str] | None = None,
    reason: str = "Create region",
) -> Region:
    """Create a Region and record an append-only audit entry."""
    scope = _require_admin_actor(actor)
    region = Region.objects.create(
        code=code.strip().upper(),
        name=name.strip(),
        headquarters_city=headquarters_city.strip(),
        states_covered=states_covered or [],
    )
    record_audit_event(
        actor=actor,
        actor_role=RoleCode.TECHNICAL_ADMIN,
        actor_scope=scope.to_audit_dict(),
        action="REGION_CREATED",
        target_type="Region",
        target_id=str(region.id),
        region=region,
        reason=reason,
        inputs_snapshot={"code": region.code, "name": region.name},
    )
    return region


@transaction.atomic
def create_bureau(
    *,
    actor: Any,
    code: str,
    name: str,
    bureau_type: str = Bureau.BureauType.REGULATION,
    reason: str = "Create bureau",
) -> Bureau:
    """Create a Bureau and record an append-only audit entry."""
    scope = _require_admin_actor(actor)
    bureau = Bureau.objects.create(
        code=code.strip().upper(),
        name=name.strip(),
        bureau_type=bureau_type,
    )
    record_audit_event(
        actor=actor,
        actor_role=RoleCode.TECHNICAL_ADMIN,
        actor_scope=scope.to_audit_dict(),
        action="BUREAU_CREATED",
        target_type="Bureau",
        target_id=str(bureau.id),
        reason=reason,
        inputs_snapshot={"code": bureau.code, "name": bureau.name, "bureau_type": bureau_type},
    )
    return bureau


@transaction.atomic
def create_institution(
    *,
    actor: Any,
    permanent_id: str,
    name: str,
    region: Region,
    category: str,
    state: str,
    trust_society_company_name: str = "",
    district: str = "",
    city: str = "",
    affiliating_body: str = "",
    is_new_institution: bool = False,
    is_women_only: bool = False,
    is_pwbd_institution: bool = False,
    reason: str = "Create institution",
) -> Institution:
    """Create an Institution and record an append-only audit entry."""
    scope = _require_admin_actor(actor)
    inst = Institution.objects.create(
        permanent_id=permanent_id.strip(),
        name=name.strip(),
        region=region,
        category=category,
        state=state.strip(),
        trust_society_company_name=trust_society_company_name.strip(),
        district=district.strip(),
        city=city.strip(),
        affiliating_body=affiliating_body.strip(),
        is_new_institution=is_new_institution,
        is_women_only=is_women_only,
        is_pwbd_institution=is_pwbd_institution,
    )
    record_audit_event(
        actor=actor,
        actor_role=RoleCode.TECHNICAL_ADMIN,
        actor_scope=scope.to_audit_dict(),
        action="INSTITUTION_CREATED",
        target_type="Institution",
        target_id=str(inst.id),
        institution=inst,
        region=region,
        reason=reason,
        inputs_snapshot={"permanent_id": inst.permanent_id, "name": inst.name, "category": category},
    )
    return inst


@transaction.atomic
def create_committee(
    *,
    actor: Any,
    code: str,
    name: str,
    committee_type: str,
    region: Region | None = None,
    bureau: Bureau | None = None,
    quorum_count: int = 2,
    valid_from: timezone.datetime | None = None,
    valid_until: timezone.datetime | None = None,
    reason: str = "Constitute committee",
) -> Committee:
    """Constitute a Committee (by TECHNICAL_ADMIN, REGIONAL_OFFICER for EVC, or BUREAU_OFFICER) with audit."""
    scope = resolve_actor_scope(actor)
    allowed = {RoleCode.TECHNICAL_ADMIN, RoleCode.REGIONAL_OFFICER, RoleCode.BUREAU_OFFICER, RoleCode.COMPETENT_AUTHORITY}
    if not (scope.roles & allowed):
        raise PermissionDenied("Actor is not authorised to constitute a committee.")
    if RoleCode.REGIONAL_OFFICER in scope.roles and region and region.id not in scope.region_ids:
        raise PermissionDenied("Regional officer cannot constitute a committee outside their region.")

    committee = Committee.objects.create(
        code=code.strip().upper(),
        name=name.strip(),
        committee_type=committee_type,
        region=region,
        bureau=bureau,
        quorum_count=quorum_count,
        valid_from=valid_from or timezone.now(),
        valid_until=valid_until,
    )
    record_audit_event(
        actor=actor,
        actor_role=",".join(sorted(scope.roles)),
        actor_scope=scope.to_audit_dict(),
        action="COMMITTEE_CONSTITUTED",
        target_type="Committee",
        target_id=str(committee.id),
        region=region,
        reason=reason,
        inputs_snapshot={"code": committee.code, "committee_type": committee_type},
    )
    return committee


@transaction.atomic
def add_committee_member(
    *,
    actor: Any,
    committee: Committee,
    user: Any,
    member_role: str = CommitteeMembership.MemberRole.ACADEMIC_EXPERT,
    valid_from: timezone.datetime | None = None,
    valid_until: timezone.datetime | None = None,
    reason: str = "Assign committee member",
) -> CommitteeMembership:
    """Add a validity-bounded member to a Committee with audit."""
    scope = resolve_actor_scope(actor)
    allowed = {RoleCode.TECHNICAL_ADMIN, RoleCode.REGIONAL_OFFICER, RoleCode.BUREAU_OFFICER, RoleCode.COMPETENT_AUTHORITY}
    if not (scope.roles & allowed):
        raise PermissionDenied("Actor is not authorised to add committee members.")

    membership = CommitteeMembership.objects.create(
        committee=committee,
        user=user,
        member_role=member_role,
        valid_from=valid_from or timezone.now(),
        valid_until=valid_until,
    )
    record_audit_event(
        actor=actor,
        actor_role=",".join(sorted(scope.roles)),
        actor_scope=scope.to_audit_dict(),
        action="COMMITTEE_MEMBER_ADDED",
        target_type="CommitteeMembership",
        target_id=str(membership.id),
        region=committee.region,
        reason=reason,
        inputs_snapshot={
            "committee_id": str(committee.id),
            "user_id": user.pk,
            "member_role": member_role,
        },
    )
    return membership
