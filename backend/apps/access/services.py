"""Deny-by-default scoped authorisation services (Sheet 01 Block 01, Sheet 06 K2, Sheet 07 P1, P5, Q2)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.access.models import CaseAssignment, REGULATORY_ROLES, RoleAssignment, RoleCode
from apps.audit.services import record_audit_event
from apps.organisation.models import CommitteeMembership


@dataclass(frozen=True)
class ActorScopeSnapshot:
    """Resolved active scope for an authenticated user at a point in time (Sheet 01 Block 01, Sheet 06 K2)."""

    user_id: int
    roles: frozenset[str]
    institution_ids: frozenset[UUID]
    region_ids: frozenset[UUID]
    bureau_ids: frozenset[UUID]
    committee_ids: frozenset[UUID]
    delegated_powers: frozenset[str]

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "roles": sorted(self.roles),
            "institution_ids": [str(x) for x in sorted(self.institution_ids, key=str)],
            "region_ids": [str(x) for x in sorted(self.region_ids, key=str)],
            "bureau_ids": [str(x) for x in sorted(self.bureau_ids, key=str)],
            "committee_ids": [str(x) for x in sorted(self.committee_ids, key=str)],
            "delegated_powers": sorted(self.delegated_powers),
        }


def resolve_actor_scope(user: Any, at_time: timezone.datetime | None = None) -> ActorScopeSnapshot:
    """Resolve active role, institution, region, bureau, and committee scopes for a user (Sheet 01 Block 01, Sheet 07 N1, P1)."""
    if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        raise PermissionDenied("Authentication is required (Deny by default — Sheet 06 K2).")

    now = at_time or timezone.now()
    assignments = RoleAssignment.objects.filter(user=user, is_active=True).select_related(
        "institution", "region", "bureau", "committee"
    )

    roles: set[str] = set()
    institution_ids: set[UUID] = set()
    region_ids: set[UUID] = set()
    bureau_ids: set[UUID] = set()
    committee_ids: set[UUID] = set()
    powers: set[str] = set()

    for ra in assignments:
        if not ra.is_currently_valid(now):
            continue
        roles.add(ra.role)
        if ra.institution_id:
            institution_ids.add(ra.institution_id)
        if ra.region_id:
            region_ids.add(ra.region_id)
        if ra.bureau_id:
            bureau_ids.add(ra.bureau_id)
        if ra.committee_id:
            committee_ids.add(ra.committee_id)
        for p in ra.delegated_powers or []:
            powers.add(str(p))

    memberships = CommitteeMembership.objects.filter(user=user, is_active=True).select_related("committee")
    for cm in memberships:
        if cm.is_currently_valid(now):
            committee_ids.add(cm.committee_id)

    if not roles:
        raise PermissionDenied("User holds no active valid role assignments (Deny by default — Sheet 06 K2).")

    return ActorScopeSnapshot(
        user_id=user.pk,
        roles=frozenset(roles),
        institution_ids=frozenset(institution_ids),
        region_ids=frozenset(region_ids),
        bureau_ids=frozenset(bureau_ids),
        committee_ids=frozenset(committee_ids),
        delegated_powers=frozenset(powers),
    )


def assert_not_technical_admin_only_for_regulatory_action(scope: ActorScopeSnapshot, action: str) -> None:
    """Enforce Sheet 07 P5: Technical admin != regulatory authority."""
    if not (scope.roles & REGULATORY_ROLES):
        raise PermissionDenied(
            f"Action '{action}' requires regulatory authority; technical/non-regulatory roles are denied (Sheet 07 P5)."
        )


def check_case_read_access(user: Any, case: Any, at_time: timezone.datetime | None = None) -> ActorScopeSnapshot:
    """Enforce deny-by-default read/detail/export scope on a case (Sheet 01 Block 01, Sheet 06 K2, Sheet 07 P1, Q2)."""
    now = at_time or timezone.now()
    scope = resolve_actor_scope(user, now)

    # Oversight auditor or Competent Authority can inspect across regions/bureaus
    if RoleCode.OVERSIGHT_AUDITOR in scope.roles or RoleCode.COMPETENT_AUTHORITY in scope.roles:
        return scope

    # Institution user: strictly own institution only
    if RoleCode.INSTITUTION_USER in scope.roles and case.institution_id in scope.institution_ids:
        return scope

    # Regional officer: strictly own region only
    if RoleCode.REGIONAL_OFFICER in scope.roles and case.region_id in scope.region_ids:
        return scope

    # Bureau officer: strictly assigned bureau or region
    if RoleCode.BUREAU_OFFICER in scope.roles:
        if (case.responsible_bureau_id and case.responsible_bureau_id in scope.bureau_ids) or (
            case.region_id in scope.region_ids
        ):
            return scope

    # Reviewers / Committee members (Scrutiny, EVC, SHC/SAC/SCSC): strictly active case or stage assignment (Sheet 07 Q2)
    if scope.roles & {RoleCode.SCRUTINY_MEMBER, RoleCode.EVC_MEMBER, RoleCode.COMMITTEE_MEMBER}:
        active_assignments = CaseAssignment.objects.filter(case=case, is_active=True)
        for ca in active_assignments:
            if not ca.is_currently_valid(now):
                continue
            if ca.user_id == user.pk:
                return scope
            if ca.committee_id and ca.committee_id in scope.committee_ids:
                return scope

    raise PermissionDenied("Cross-institution, cross-region, or unassigned case access denied (Sheet 07 P1, Q2).")


def check_stage_execution_access(
    user: Any,
    case: Any,
    stage_instance: Any,
    action: str,
    at_time: timezone.datetime | None = None,
) -> ActorScopeSnapshot:
    """Enforce strict stage assignment and role scope under lock before stage mutation (Sheet 02 B1, Sheet 06 K2, Sheet 07 Q2)."""
    now = at_time or timezone.now()
    scope = resolve_actor_scope(user, now)
    assert_not_technical_admin_only_for_regulatory_action(scope, action)

    policy = case.pinned_policy_version
    permitted = (policy.committee_permissions or {}).get(stage_instance.stage_type) if policy else None
    if permitted is not None and not scope.roles.intersection(permitted):
        raise PermissionDenied("Pinned policy does not permit this role to execute the stage.")

    # Check explicit assignment to this stage or case
    has_direct_stage_assignment = stage_instance.assigned_officer_id == user.pk or (
        stage_instance.assigned_committee_id and stage_instance.assigned_committee_id in scope.committee_ids
    )
    if not has_direct_stage_assignment:
        assignments = CaseAssignment.objects.filter(case=case, is_active=True)
        for ca in assignments:
            if not ca.is_currently_valid(now):
                continue
            if ca.stage_instance_id in (None, stage_instance.id):
                if ca.user_id == user.pk or (ca.committee_id and ca.committee_id in scope.committee_ids):
                    has_direct_stage_assignment = True
                    break

    # Regional/Bureau officers may only act within their region/bureau AND when assigned or owning the stage
    if RoleCode.REGIONAL_OFFICER in scope.roles and case.region_id not in scope.region_ids:
        raise PermissionDenied("Regional officer cannot execute stage outside assigned region (Sheet 07 Q2).")

    if not has_direct_stage_assignment:
        raise PermissionDenied("Unassigned reviewer or committee member is denied stage execution (Sheet 07 Q2).")

    return scope


@transaction.atomic
def assign_role_to_user(
    *,
    actor: Any,
    target_user: Any,
    role: str,
    reason: str,
    institution: Any = None,
    region: Any = None,
    bureau: Any = None,
    committee: Any = None,
    delegated_powers: list[str] | None = None,
    valid_from: timezone.datetime | None = None,
    valid_until: timezone.datetime | None = None,
) -> RoleAssignment:
    """Create a validity-bounded RoleAssignment with mandatory audit record (PS Administration, Sheet 07 N1, P5)."""
    actor_scope = resolve_actor_scope(actor)
    if RoleCode.TECHNICAL_ADMIN not in actor_scope.roles:
        raise PermissionDenied("Only TECHNICAL_ADMIN may manage role assignments (PS Administration).")
    if not reason.strip():
        raise PermissionDenied("An explicit audit reason is required for role assignment.")

    ra = RoleAssignment(
        user=target_user,
        role=role,
        institution=institution,
        region=region,
        bureau=bureau,
        committee=committee,
        delegated_powers=delegated_powers or [],
        valid_from=valid_from or timezone.now(),
        valid_until=valid_until,
        is_active=True,
        assigned_reason=reason,
    )
    ra.full_clean()
    ra.save()

    record_audit_event(
        actor=actor,
        actor_role=RoleCode.TECHNICAL_ADMIN,
        actor_scope=actor_scope.to_audit_dict(),
        action="ROLE_ASSIGNMENT_CREATED",
        target_type="RoleAssignment",
        target_id=str(ra.id),
        institution=institution,
        region=region,
        reason=reason,
        inputs_snapshot={
            "target_user_id": target_user.pk,
            "role": role,
            "delegated_powers": delegated_powers or [],
        },
    )
    return ra


@transaction.atomic
def create_case_assignment(
    *,
    actor: Any,
    case: Any,
    assignment_scope: str,
    reason: str,
    stage_instance: Any = None,
    target_user: Any = None,
    target_committee: Any = None,
    valid_from: timezone.datetime | None = None,
    valid_until: timezone.datetime | None = None,
) -> CaseAssignment:
    """Create an audited case/stage reviewer or committee assignment with validity window (Sheet 04 J5, Sheet 07 N1, P5)."""
    actor_scope = resolve_actor_scope(actor)
    allowed_assigners = {
        RoleCode.REGIONAL_OFFICER,
        RoleCode.BUREAU_OFFICER,
        RoleCode.COMPETENT_AUTHORITY,
        RoleCode.TECHNICAL_ADMIN,
    }
    if not (actor_scope.roles & allowed_assigners):
        raise PermissionDenied("Actor is not authorised to assign case/stage reviewers.")
    if RoleCode.REGIONAL_OFFICER in actor_scope.roles and case.region_id not in actor_scope.region_ids:
        raise PermissionDenied("Regional officer cannot assign cases outside their region.")
    if not reason.strip():
        raise PermissionDenied("Assignment requires an explicit recorded reason (Sheet 04 J5, Sheet 07 P5).")

    if RoleCode.BUREAU_OFFICER in actor_scope.roles and RoleCode.TECHNICAL_ADMIN not in actor_scope.roles:
        check_case_read_access(actor, case)
    if (target_user is None) == (target_committee is None):
        raise ValidationError("Assign exactly one user or committee.")
    if stage_instance is not None and stage_instance.case_id != case.id:
        raise ValidationError("Stage does not belong to the case.")
    if assignment_scope not in CaseAssignment.AssignmentScope.values:
        raise ValidationError("Invalid assignment scope.")
    if valid_until and valid_until <= (valid_from or timezone.now()):
        raise ValidationError("Assignment validity end must follow its start.")

    ca = CaseAssignment.objects.create(
        case=case,
        stage_instance=stage_instance,
        user=target_user,
        committee=target_committee,
        assignment_scope=assignment_scope,
        valid_from=valid_from or timezone.now(),
        valid_until=valid_until,
        is_active=True,
        reason=reason,
    )
    if stage_instance:
        if target_user:
            stage_instance.assigned_officer = target_user
        if target_committee:
            stage_instance.assigned_committee = target_committee
        stage_instance.save(update_fields=["assigned_officer", "assigned_committee", "updated_at"])

    record_audit_event(
        actor=actor,
        actor_role=",".join(sorted(actor_scope.roles)),
        actor_scope=actor_scope.to_audit_dict(),
        action="CASE_ASSIGNMENT_CREATED",
        target_type="CaseAssignment",
        target_id=str(ca.id),
        case=case,
        reason=reason,
        inputs_snapshot={
            "assignment_scope": assignment_scope,
            "target_user_id": getattr(target_user, "pk", None),
            "target_committee_id": str(target_committee.id) if target_committee else None,
            "stage_instance_id": str(stage_instance.id) if stage_instance else None,
        },
    )
    return ca
